/*
Copyright 2024.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

package controller

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"os"
	"reflect"
	"strconv"
	"strings"
	"time"

	"sigs.k8s.io/yaml"

	kyvernov1 "github.com/kyverno/kyverno/api/kyverno/v1"
	kyvernov2 "github.com/kyverno/kyverno/api/kyverno/v2"
	core "k8s.io/api/core/v1"
	apiextv1 "k8s.io/apiextensions-apiserver/pkg/apis/apiextensions/v1"
	"k8s.io/apimachinery/pkg/api/equality"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/api/meta"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/client-go/util/retry"
	serving "knative.dev/serving/pkg/apis/serving/v1"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/client/config"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
	"sigs.k8s.io/controller-runtime/pkg/log"

	k8smofaascomv1 "mofaas/api/v1"
)

const mofaasFunctionFinalizer = "mofaasfunctions.mofaas.atnog/finalizer"

const envoyConfigPath = "config/envoy/envoy.yaml"
const kyvernoPolExceptPath = "config/kyverno/policy-exception.yaml"
const kyvernoPolPath = "config/kyverno/policy.yaml"

// Definitions to manage status conditions
const (
	// typeAvailableMoFaaSFunction represents the status of the MoFaaSFunction reconciliation
	typeAvailableMoFaaSFunction = "Available"
	// typeDegradedMoFaaSFunction represents the status used when the custom resource is deleted and the finalizer operations are yet to occur.
	typeDegradedMoFaaSFunction = "Degraded"
)

// MoFaaSFunctionReconciler reconciles a MoFaaSFunction object
type MoFaaSFunctionReconciler struct {
	client.Client
	Scheme *runtime.Scheme
	// Mine
	FunctionChooserImage string
	EgressProxyImage     string
}

// +kubebuilder:rbac:groups=mofaas.atnog,resources=mofaasfunctions,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=mofaas.atnog,resources=mofaasfunctions/status,verbs=get;update;patch
// +kubebuilder:rbac:groups=mofaas.atnog,resources=mofaasfunctions/finalizers,verbs=update

// Reconcile is part of the main kubernetes reconciliation loop which aims to
// move the current state of the cluster closer to the desired state.
// TODO(user): Modify the Reconcile function to compare the state specified by
// the MoFaaSFunction object against the actual cluster state, and then
// perform operations to make the cluster state reflect the state specified by
// the user.
//
// For more details, check Reconcile and its Result here:
// - https://pkg.go.dev/sigs.k8s.io/controller-runtime@v0.19.0/pkg/reconcile
func (r *MoFaaSFunctionReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	log := log.FromContext(ctx)

	var mofaasFunc k8smofaascomv1.MoFaaSFunction
	if err := r.Get(ctx, req.NamespacedName, &mofaasFunc); err != nil {
		if apierrors.IsNotFound(err) {
			// If the custom resource is not found then it usually means that it was deleted or not created
			// In this way, we will stop the reconciliation
			log.Info("MoFaaSFunction resource not found. Ignoring since object must be deleted")
			return ctrl.Result{}, nil
		}
		log.Error(err, "Unable to fetch MoFaaSFunction")
		return ctrl.Result{}, client.IgnoreNotFound(err)
	}

	// First, let's create the egress proxy service if the concurrency is greater than 1
	// TODO -> this code should really be improved, it is starting to be too spaghetti :(
	egressProxyService := serving.Service{
		TypeMeta: metav1.TypeMeta{
			APIVersion: serving.Kind("Service").Group + "/v1", Kind: "Service",
		},
		ObjectMeta: metav1.ObjectMeta{
			Name:      "mofaas-egress-proxy-" + mofaasFunc.Name,
			Namespace: mofaasFunc.Namespace,
			Labels: map[string]string{"networking.knative.dev/visibility": "cluster-local"},
		},
	}
	configMapName := fmt.Sprintf("%s-envoy-config", mofaasFunc.Name)
	policyExceptionName := fmt.Sprintf("%s-policy-exception", mofaasFunc.Name)
	policyName := fmt.Sprintf("%s-policy", mofaasFunc.Name)
	if mofaasFunc.Spec.Concurrency > 1 {
		_, err := controllerutil.CreateOrUpdate(ctx, r.Client, &egressProxyService, func() error {
			err := r.generateEgressProxyServiceStruct(ctx, mofaasFunc, &egressProxyService)
			return err
		})
		if err != nil {
			log.Error(err, "Unable to update or create the Egress Proxy Service")
			return ctrl.Result{}, err
		}

		/***************************************** UPDATE ASSOCIATED VARIANTS' KNATIVE SERVICES LABELS *****************************************/
		// Define the new labels to be added
		newLabels := map[string]string{
			fmt.Sprintf("%s/mofaasfunction", k8smofaascomv1.GroupVersion.Group): mofaasFunc.Name,
		}

		// Iterate over each variant and update its service labels
		for _, variant := range mofaasFunc.Spec.Variants {
			err := updatePodLabels(ctx, r.Client, mofaasFunc.Namespace, variant.Name, newLabels)
			if err != nil {
				log.Error(err, "Error updating service labels", "namespace", mofaasFunc.Namespace, "service", variant.Name)
				// Decide whether to continue or return the error based on your use case
			}
		}

		// Then, create the new configmap for the envoy
		r.createAndMountConfigMap(ctx, &mofaasFunc, &egressProxyService, newLabels, configMapName, policyExceptionName, policyName)
	} else {
		// Delete the egress proxy service if it exists.
		err := r.Client.Delete(ctx, &egressProxyService)

		// Ignore the error if the service is not found.
		if err != nil && !apierrors.IsNotFound(err) {
			log.Error(err, "Unable to delete the Egress Proxy Service")
			return ctrl.Result{}, err
		}

		// Delete the ConfigMap if it exists.
		configMap := &core.ConfigMap{
			ObjectMeta: metav1.ObjectMeta{
				Name:      configMapName,
				Namespace: mofaasFunc.Namespace,
			},
		}
		if err := r.Client.Delete(ctx, configMap); err != nil && !apierrors.IsNotFound(err) {
			log.Error(err, "Unable to delete ConfigMap")
			return ctrl.Result{}, err
		}
	
		// Delete the PolicyException if it exists.
		policyException := &kyvernov2.PolicyException{
			ObjectMeta: metav1.ObjectMeta{
				Name:      policyExceptionName,
				Namespace: mofaasFunc.Namespace,
			},
		}
		if err := r.Client.Delete(ctx, policyException); err != nil && !apierrors.IsNotFound(err) {
			log.Error(err, "Unable to delete PolicyException")
			return ctrl.Result{}, err
		}
	
		// Delete the Policy if it exists.
		policy := &kyvernov1.Policy{
			ObjectMeta: metav1.ObjectMeta{
				Name:      policyName,
				Namespace: mofaasFunc.Namespace,
			},
		}
		if err := r.Client.Delete(ctx, policy); err != nil && !apierrors.IsNotFound(err) {
			log.Error(err, "Unable to delete Policy")
			return ctrl.Result{}, err
		}
	}

	// Status as Unknown when no status is available
	// Adapted from https://github.com/kubernetes-sigs/kubebuilder/blob/master/docs/book/src/getting-started/testdata/project/internal/controller/memcached_controller.go
	if mofaasFunc.Status.Conditions == nil || len(mofaasFunc.Status.Conditions) == 0 {
		meta.SetStatusCondition(&mofaasFunc.Status.Conditions, metav1.Condition{Type: typeAvailableMoFaaSFunction, Status: metav1.ConditionUnknown, Reason: "Reconciling", Message: "Starting reconciliation"})
		if err := r.Status().Update(ctx, &mofaasFunc); err != nil {
			log.Error(err, "Failed to update MoFaaSFunction status")
			return ctrl.Result{}, err
		}

		// Let's re-fetch the MoFaaSFunction Custom Resource after updating the status
		// so that we have the latest state of the resource on the cluster and we will avoid
		// raising the error "the object has been modified, please apply
		// your changes to the latest version and try again" which would re-trigger the reconciliation
		// if we try to update it again in the following operations
		if err := r.Get(ctx, req.NamespacedName, &mofaasFunc); err != nil {
			log.Error(err, "Failed to re-fetch MoFaaSFunction")
			return ctrl.Result{}, err
		}
	}

	// Let's be sure we have the latest version
	if err := r.Get(ctx, req.NamespacedName, &mofaasFunc); err != nil {
		log.Error(err, "Failed to re-fetch MoFaaSFunction")
		return ctrl.Result{}, err
	}

	// Let's add a finalizer. Then, we can define some operations which should
	// occur before the custom resource is deleted.
	// More info: https://kubernetes.io/docs/concepts/overview/working-with-objects/finalizers
	if !controllerutil.ContainsFinalizer(&mofaasFunc, mofaasFunctionFinalizer) {
		log.Info("Adding Finalizer for MoFaaSFunction")

		// Retry on conflict to avoid stale object updates.
		err := retry.RetryOnConflict(retry.DefaultRetry, func() error {
			// Re-fetch the latest version of the object
			var latestFunc k8smofaascomv1.MoFaaSFunction
			if err := r.Get(ctx, req.NamespacedName, &latestFunc); err != nil {
				return err
			}

			// Check if the finalizer was already added by another concurrent reconciliation.
			if controllerutil.ContainsFinalizer(&latestFunc, mofaasFunctionFinalizer) {
				return nil
			}

			// Add the finalizer
			controllerutil.AddFinalizer(&latestFunc, mofaasFunctionFinalizer)

			// Update the object with the new finalizer
			if err := r.Update(ctx, &latestFunc); err != nil {
				return err
			}
			return nil
		})

		if err != nil {
			log.Error(err, "Failed to update custom resource to add finalizer")
			return ctrl.Result{}, err
		}
	}

	/***************************************** DELETE *****************************************/
	// Check if the Memcached instance is marked to be deleted, which is
	// indicated by the deletion timestamp being set.
	isMofaasFunctMarkedToBeDeleted := mofaasFunc.GetDeletionTimestamp() != nil
	if isMofaasFunctMarkedToBeDeleted {
		if controllerutil.ContainsFinalizer(&mofaasFunc, mofaasFunctionFinalizer) {
			log.Info("Performing Finalizer Operations for MoFaaSFunction before delete CR")

			// Let's add here a status "Downgrade" to reflect that this resource began its process to be terminated.
			meta.SetStatusCondition(&mofaasFunc.Status.Conditions, metav1.Condition{Type: typeDegradedMoFaaSFunction,
				Status: metav1.ConditionUnknown, Reason: "Finalizing",
				Message: fmt.Sprintf("Performing finalizer operations for the custom resource: %s ", mofaasFunc.Name)})

			if err := r.Status().Update(ctx, &mofaasFunc); err != nil {
				log.Error(err, "Failed to update MoFaaSFunction status")
				return ctrl.Result{}, err
			}

			// Re-fetch the MoFaaSFunction Custom Resource before updating the status
			// so that we have the latest state of the resource on the cluster and we will avoid
			// raising the error "the object has been modified, please apply
			// your changes to the latest version and try again" which would re-trigger the reconciliation
			if err := r.Get(ctx, req.NamespacedName, &mofaasFunc); err != nil {
				log.Error(err, "Failed to re-fetch MoFaaSFunction")
				return ctrl.Result{}, err
			}

			meta.SetStatusCondition(&mofaasFunc.Status.Conditions, metav1.Condition{Type: typeDegradedMoFaaSFunction,
				Status: metav1.ConditionTrue, Reason: "Finalizing",
				Message: fmt.Sprintf("Finalizer operations for custom resource %s name were successfully accomplished", mofaasFunc.Name)})

			if err := r.Status().Update(ctx, &mofaasFunc); err != nil {
				log.Error(err, "Failed to update MoFaaSFunction status")
				return ctrl.Result{}, err
			}

			log.Info("Removing Finalizer for MoFaaSFunction after successfully perform the operations")
			if ok := controllerutil.RemoveFinalizer(&mofaasFunc, mofaasFunctionFinalizer); !ok {
				log.Error(nil, "Failed to remove finalizer for MoFaaSFunction")
				return ctrl.Result{Requeue: true}, nil
			}

			if err := r.Update(ctx, &mofaasFunc); err != nil {
				log.Error(err, "Failed to remove finalizer for MoFaaSFunction")
				return ctrl.Result{}, err
			}
		}
		return ctrl.Result{}, nil
	}

	/***************************************** Generate MoFaaS Controller Knative Service structure *****************************************/
	functionChooserServiceLabels := map[string]string{}
	if mofaasFunc.Spec.Private {
		functionChooserServiceLabels["networking.knative.dev/visibility"] = "cluster-local"
	}
	functionChooserService := serving.Service{
		TypeMeta: metav1.TypeMeta{
			APIVersion: serving.Kind("Service").Group + "/v1", Kind: "Service",
		},
		ObjectMeta: metav1.ObjectMeta{
			Name:      "mofaas-chooser-" + mofaasFunc.Name,
			Namespace: mofaasFunc.Namespace,
			Labels: functionChooserServiceLabels,
		},
	}

	/***************************************** CREATE OR UPDATE *****************************************/
	// Create or update the Knative Service for the Function Chooser
	// TODO - MAYBE IN THE FUTURE, WE SHOULD VERIFY IF THE SERVICE WAS CREATED COMPLETELY WITH SUCCESS (E.G., IT MIGHT FAIL IF THE CONTAINER IS NOT FOUND)
	result, err := controllerutil.CreateOrUpdate(ctx, r.Client, &functionChooserService, func() error {
		err := r.generateFuncChooserServiceStruct(ctx, mofaasFunc, &functionChooserService, egressProxyService.Name)
		return err
	})

	if err != nil {
		log.Error(err, "Unable to update or create the Function Chooser Knative Service")
		return ctrl.Result{}, err
	} else if result == controllerutil.OperationResultCreated || result == controllerutil.OperationResultUpdated {
		if err := r.updateStatusOnCreateOrUpdate(ctx, &mofaasFunc, functionChooserService); err != nil {
			log.Error(err, "Failed to update MoFaaSFunction status after Controller Knative Service "+string(result))
			return ctrl.Result{}, err
		}
	} else if result == controllerutil.OperationResultNone {
		log.Info("Did not update nor created a MoFaaSFunction object")
	}

	// Adapted from https://github.com/kubernetes-sigs/kubebuilder/blob/master/docs/book/src/getting-started/testdata/project/internal/controller/memcached_controller.go
	// meta.SetStatusCondition(&mofaasFunc.Status.Conditions, metav1.Condition{
	// 	Type:    typeAvailableMoFaaSFunction,
	// 	Status:  metav1.ConditionTrue,
	// 	Reason:  "Reconciling",
	// 	Message: fmt.Sprintf("Knative Service for custom resource (%s) created successfully", mofaasFunc.Name),
	// })
	// // Finally, update the status once with retry:
	// err = retry.RetryOnConflict(retry.DefaultRetry, func() error {
	// 	var latestFunc k8smofaascomv1.MoFaaSFunction
	// 	if err := r.Get(ctx, req.NamespacedName, &latestFunc); err != nil {
	// 		return err
	// 	}
	// 	// Apply the accumulated changes from mofaasFunc to latestFunc:
	// 	latestFunc.Status = mofaasFunc.Status
	// 	return r.Status().Update(ctx, &latestFunc)
	// })
	// if err != nil {
	// 	log.Error(err, "Failed to update MoFaaSFunction status at final step")
	// 	return ctrl.Result{}, err
	// }

	return ctrl.Result{}, nil
}

func (r *MoFaaSFunctionReconciler) updateStatusOnCreateOrUpdate(ctx context.Context, mofaasFunc *k8smofaascomv1.MoFaaSFunction, controllerService serving.Service) error {
	log := log.FromContext(ctx)

	timeoutCtx, cancel := context.WithTimeout(context.Background(), time.Second*60) // TODO - MAYBE THIS SHOULD BE PASSED BY ARGUMENT
	defer cancel()

	var svc serving.Service
	for {
		// Let's be sure we have the latest version
		err := r.Get(ctx, types.NamespacedName{Namespace: controllerService.Namespace, Name: controllerService.Name}, &svc)
		if err != nil {
			if apierrors.IsNotFound(err) {
				log.Info("Knative Service not found yet; waiting...", "namespace", controllerService.Namespace, "name", controllerService.Name)
			} else {
				// For any other error, log it and wait.
				log.Error(err, "Error fetching the Knative Service; will retry", "namespace", controllerService.Namespace, "name", controllerService.Name)
			}
		} else {
			// Service found. Check if it has the address and URL.
			if svc.Status.Address != nil && svc.Status.URL != nil {
				// Update the custom resource status from the Knative Service.
				mofaasFunc.Status.Address = svc.Status.Address.DeepCopy()
				mofaasFunc.Status.URL = svc.Status.URL.DeepCopy()
				break
			} else {
				log.Info("Knative Service found but not ready yet", "namespace", controllerService.Namespace, "name", controllerService.Name)
			}
		}

		select {
		case <-time.After(time.Second): // Every second
		case <-timeoutCtx.Done():
			log.Error(timeoutCtx.Err(), "Error while waiting for the Knative Service address")
			return timeoutCtx.Err()
		}
	}

	// Now update the status only if something has changed.
	err := retry.RetryOnConflict(retry.DefaultRetry, func() error {
		var latestFunc k8smofaascomv1.MoFaaSFunction
		if err := r.Get(ctx, types.NamespacedName{Namespace: mofaasFunc.Namespace, Name: mofaasFunc.Name}, &latestFunc); err != nil {
			return err
		}

		// Define the desired status values.
		desiredController := controllerService.Name
		desiredAddress := svc.Status.Address.DeepCopy()
		desiredURL := svc.Status.URL.DeepCopy()
		desiredCondition := metav1.Condition{
			Type:    typeAvailableMoFaaSFunction,
			Status:  metav1.ConditionTrue,
			Reason:  "Reconciling",
			Message: fmt.Sprintf("Knative Service for custom resource (%s) created or updated successfully", latestFunc.Name),
		}

		// Check if an update is actually needed.
		updateNeeded := false
		if latestFunc.Status.Controller != desiredController {
			updateNeeded = true
		}
		if !equality.Semantic.DeepEqual(latestFunc.Status.Address, desiredAddress) {
			updateNeeded = true
		}
		if !equality.Semantic.DeepEqual(latestFunc.Status.URL, desiredURL) {
			updateNeeded = true
		}

		currentCondition := meta.FindStatusCondition(latestFunc.Status.Conditions, desiredCondition.Type)
		if currentCondition == nil || !equality.Semantic.DeepEqual(currentCondition.Status, desiredCondition.Status) ||
			!equality.Semantic.DeepEqual(currentCondition.Reason, desiredCondition.Reason) ||
			!equality.Semantic.DeepEqual(currentCondition.Message, desiredCondition.Message) {
			updateNeeded = true
		}

		// If nothing changed, skip the update.
		if !updateNeeded {
			log.Info("Status is up-to-date, skipping update", "controller", desiredController)
			return nil
		}

		// Otherwise, update the status.
		latestFunc.Status.Controller = desiredController
		latestFunc.Status.Address = desiredAddress
		latestFunc.Status.URL = desiredURL
		meta.SetStatusCondition(&latestFunc.Status.Conditions, desiredCondition)

		if err := r.Status().Update(ctx, &latestFunc); err != nil {
			return err
		}
		return nil
	})
	if err != nil {
		log.Error(err, "Failed to update MoFaaSFunction status")
		return err
	}

	log.Info("Updated MoFaaSFunc Status with success after creation or update")

	return nil
}

func (r *MoFaaSFunctionReconciler) generateEgressProxyServiceStruct(ctx context.Context, mofaasFunc k8smofaascomv1.MoFaaSFunction, egressProxyService *serving.Service) error {
	log := log.FromContext(ctx)

	// Knative Service definition for the Proxy
	// egressProxyService.TypeMeta = metav1.TypeMeta{APIVersion: serving.Kind("Service").Group + "/v1", Kind: "Service"}
	// egressProxyService.ObjectMeta.Name = "mofaas-egress-proxy-" + mofaasFunc.Name
	// egressProxyService.ObjectMeta.Namespace = mofaasFunc.Namespace
	egressProxyService.Spec = serving.ServiceSpec{
		ConfigurationSpec: serving.ConfigurationSpec{
			Template: serving.RevisionTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{
					Labels: map[string]string{
						fmt.Sprintf("%s/service", k8smofaascomv1.GroupVersion.Group): "mofaas-egress-proxy", // TODO -> THIS SHOULD BE DEFINED AS A CONSTANT OR SOMETHING
						"networking.knative.dev/visibility": "cluster-local",
					},
				},
				Spec: serving.RevisionSpec{
					PodSpec: core.PodSpec{
						Containers: []core.Container{
							{
								// Name:  "function-chooser",
								Image: r.EgressProxyImage,
							},
						},
					},
				},
			},
		},
	}

	if err := ctrl.SetControllerReference(&mofaasFunc, egressProxyService, r.Scheme); err != nil {
		log.Error(err, "Error while setting controller reference for Egress Proxy")
		return err
	}

	return nil
}

func (r *MoFaaSFunctionReconciler) generateFuncChooserServiceStruct(ctx context.Context, mofaasFunc k8smofaascomv1.MoFaaSFunction, functionChooserService *serving.Service, egressProxyServiceName string) error {
	log := log.FromContext(ctx)

	// First, get the headers to ignore
	ignoreHeadersEnc := make([]string, len(mofaasFunc.Spec.DeepCopy().IgnoreHeaders))
	for i, header := range mofaasFunc.Spec.IgnoreHeaders {
		ignoreHeadersEnc[i] = base64.StdEncoding.EncodeToString([]byte(header))
	}

	// Second, get the Knative Services' URLs MoFaaS has to protect
	srvEncURLs := make([]string, len(mofaasFunc.Spec.Variants))
	services := make([]string, len(mofaasFunc.Spec.Variants))
	for i, variant := range mofaasFunc.Spec.Variants {
		currentUrl, err := r.getKnativeServiceURL(ctx, variant.Name, mofaasFunc.Namespace)
		if err != nil {
			log.Error(err, fmt.Sprintf("Error while obtaining the variant's URLs for mofaasFunc %s in namespace %s", mofaasFunc.Name, mofaasFunc.Namespace))
			return err
		}
		srvEncURLs[i] = base64.StdEncoding.EncodeToString([]byte(currentUrl))
		services[i] = variant.Name
	}

	// Knative Service definition for the Function Chooser
	// functionChooserService.TypeMeta = metav1.TypeMeta{APIVersion: serving.Kind("Service").Group + "/v1", Kind: "Service"}
	// functionChooserService.ObjectMeta.Name = "mofaas-chooser-" + mofaasFunc.Name
	// functionChooserService.ObjectMeta.Namespace = mofaasFunc.Namespace
	functionChooserService.Spec = serving.ServiceSpec{
		ConfigurationSpec: serving.ConfigurationSpec{
			Template: serving.RevisionTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{
					Labels: map[string]string{
						fmt.Sprintf("%s/service", k8smofaascomv1.GroupVersion.Group): "mofaas-chooser", // TODO -> THIS SHOULD BE DEFINED AS A CONSTANT OR SOMETHING
					},
				},
				Spec: serving.RevisionSpec{
					PodSpec: core.PodSpec{
						Containers: []core.Container{
							{
								// Name:  "function-chooser",
								Image: r.FunctionChooserImage,
								Env: []core.EnvVar{
									{
										Name:  "SERVICES",
										Value: strings.Join(services[:], ","),
									},
									{
										Name:  "SERVICES_URLS",
										Value: strings.Join(srvEncURLs[:], ","),
									},
									{
										Name:  "CONCURRENCY",
										Value: strconv.Itoa(mofaasFunc.Spec.Concurrency),
									},
									{
										Name:  "IGNORE_HEADERS",
										Value: strings.Join(ignoreHeadersEnc[:], ","),
									},
								},
							},
						},
					},
				},
			},
		},
	}

	// Finally, get the Knative Egress Service URL if it exists and add it
	if mofaasFunc.Spec.Concurrency > 1 {
		egressProxyServiceUrl, err := r.getKnativeServiceURL(ctx, egressProxyServiceName, mofaasFunc.Namespace)
		if err != nil {
			log.Error(err, fmt.Sprintf("Error while obtaining the Egress's URLs for mofaasFunc %s in namespace %s", mofaasFunc.Name, mofaasFunc.Namespace))
			return err
		}
		egressUrlEnv := core.EnvVar{
			Name:  "EGRESS_URL",
			Value: base64.StdEncoding.EncodeToString([]byte(egressProxyServiceUrl)),
		}
		functionChooserService.Spec.ConfigurationSpec.Template.Spec.PodSpec.Containers[0].Env = append(functionChooserService.Spec.ConfigurationSpec.Template.Spec.PodSpec.Containers[0].Env, egressUrlEnv)
	}

	if err := ctrl.SetControllerReference(&mofaasFunc, functionChooserService, r.Scheme); err != nil {
		log.Error(err, "Error while setting controller reference for Function Chooser")
		return err
	}

	return nil
}

func (r *MoFaaSFunctionReconciler) getKnativeServiceURL(ctx context.Context, serviceName string, namespace string) (string, error) {
	log := log.FromContext(ctx)

	timeoutCtx, cancel := context.WithTimeout(context.Background(), time.Second*60) // TODO - MAYBE THIS SHOULD BE PASSED BY ARGUMENT
	defer cancel()

	for {
		srvObj, err := r.listObjectsByName(ctx, serviceName, namespace)
		if err != nil {
			log.Error(err, "Error while listing services")
			return "", err
		}

		if srvObj.IsReady() {
			// log.Info(srvObj.Status.Address.URL.String())
			return srvObj.Status.Address.URL.String(), nil
			// return base64.StdEncoding.EncodeToString([]byte(currentUrl)), nil
		}

		select {
		case <-time.After(time.Second / 10): // Every 100 ms
		case <-timeoutCtx.Done():
			log.Error(timeoutCtx.Err(), "Error while waiting for the Knative Service "+srvObj.Name)
			return "", timeoutCtx.Err()
		}
	}
}

/*
WITH THE HELP OF ChatGPT
*/
func (r *MoFaaSFunctionReconciler) listObjectsByName(ctx context.Context, name, namespace string) (serving.Service, error) {
	scheme := r.Scheme
	// Get a Kubernetes client using the controller-runtime package
	cfg, err := config.GetConfig()
	if err != nil {
		return serving.Service{}, err
	}

	// Create a new client
	c, err := client.New(cfg, client.Options{Scheme: scheme})
	if err != nil {
		return serving.Service{}, err
	}

	var srvObj serving.Service

	// Use the client to list objects
	err = c.Get(ctx, client.ObjectKey{
		Namespace: namespace,
		Name:      name,
	}, &srvObj)

	if err != nil {
		return serving.Service{}, err
	}

	return srvObj, nil
}

/*
WITH THE HELP OF Llama 3.1 70B
*/
func updateStruct(dst, src interface{}) {
	dstValue := reflect.ValueOf(dst).Elem()
	srcValue := reflect.ValueOf(src)

	for i := 0; i < srcValue.NumField(); i++ {
		fieldName := srcValue.Type().Field(i).Name
		if field := dstValue.FieldByName(fieldName); field.CanSet() {
			field.Set(srcValue.Field(i))
		}
	}
}

// SetupWithManager sets up the controller with the Manager.
func (r *MoFaaSFunctionReconciler) SetupWithManager(mgr ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(mgr).
		For(&k8smofaascomv1.MoFaaSFunction{}).
		Complete(r)
}

func updatePodLabels(ctx context.Context, c client.Client, namespace, serviceName string, newLabels map[string]string) error {
	// Retrieve the existing Knative Service
	service := &serving.Service{}
	err := c.Get(ctx, client.ObjectKey{Namespace: namespace, Name: serviceName}, service)
	if err != nil {
		return fmt.Errorf("failed to get service %s: %v", serviceName, err)
	}

	// Ensure the spec.template.metadata.labels map is initialized
	if service.Spec.Template.ObjectMeta.Labels == nil {
		service.Spec.Template.ObjectMeta.Labels = make(map[string]string)
	}

	// Update the labels
	for key, value := range newLabels {
		service.Spec.Template.ObjectMeta.Labels[key] = value
	}

	// Apply the update
	err = c.Update(ctx, service)
	if err != nil {
		return fmt.Errorf("failed to update service %s: %v", serviceName, err)
	}
	return nil
}

// func (r *MoFaaSFunctionReconciler) updateServiceLabels(ctx context.Context, c client.Client, namespace, serviceName string, newLabels map[string]string) error {
// 	log := log.FromContext(ctx)

// 	// Retrieve the existing service
// 	service := &serving.Service{}

// 	log.Info(fmt.Sprintf("Namespace: %s", namespace))
// 	err := c.Get(ctx, client.ObjectKey{Namespace: namespace, Name: serviceName}, service)
// 	if err != nil {
// 		log.Info(fmt.Sprintf("Failed to get service %s. Probably it was deleted. Error: %s", serviceName, err.Error()))
// 		return nil // fmt.Errorf("failed to get service %s: %v", serviceName, err)
// 	}

// 	// Update the labels
// 	if service.Labels == nil {
// 		service.Labels = make(map[string]string)
// 	}
// 	for key, value := range newLabels {
// 		service.Spec.ConfigurationSpec.Template.ObjectMeta.Labels[key] = value
// 		// service.Labels[key] = value
// 	}

// 	// Apply the update
// 	err = c.Update(ctx, service)
// 	if err != nil {
// 		return fmt.Errorf("failed to update service %s: %v", serviceName, err)
// 	}
// 	return nil
// }

func (r *MoFaaSFunctionReconciler) createAndMountConfigMap(ctx context.Context, mofaasFunc *k8smofaascomv1.MoFaaSFunction, egressProxyService *serving.Service, labels map[string]string, configMapName string, policyExceptionName string, policyName string) error {
	log := log.FromContext(ctx)

	// First, let's Load and Update Envoy Config
	var config map[string]interface{}
	if err := loadYaml(envoyConfigPath, &config); err != nil {
		log.Error(err, "Failed to load Envoy config")
		return err
	}

	// Now, let's obtain the egress proxy URL
	var address string
	address, err := r.getKnativeServiceURL(ctx, egressProxyService.Name, egressProxyService.Namespace)
	if err != nil {
		log.Error(err, fmt.Sprintf("Failed to get Egress Proxy URL for MoFaaSFunc %s in the namespace %s", mofaasFunc.Name, mofaasFunc.Namespace))
		return err
	}

	// Assume the new address comes from some object created by the controller
	err = updateEnvoyAddress(config, address)
	if err != nil {
		log.Error(err, "Failed to update Envoy config")
		return err
	}

	// Convert YAML back to string
	updatedYAML, err := yaml.Marshal(config)
	if err != nil {
		log.Error(err, "Failed to serialize updated Envoy config")
		return err
	}

	// Second, Create ConfigMap Object
	configMap := &core.ConfigMap{
		ObjectMeta: metav1.ObjectMeta{
			Name:      configMapName,
			Namespace: mofaasFunc.Namespace,
			Labels:    map[string]string{"app": mofaasFunc.Name},
		},
		Data: map[string]string{
			"envoy.yaml": string(updatedYAML),
		},
	}

	if err := controllerutil.SetControllerReference(mofaasFunc, configMap, r.Scheme); err != nil {
		log.Error(err, "Error while setting controller reference for the ConfigMap")
		return err
	}

	// Third, Apply ConfigMap in Cluster
	err = r.Client.Create(ctx, configMap)
	if err != nil && !apierrors.IsAlreadyExists(err) {
		log.Error(err, "Failed to create ConfigMap")
		return err
	}

	log.Info("Created ConfigMap successfully", "name", configMapName)

	// Fourth, Mount ConfigMap into Services
	for _, service := range mofaasFunc.Spec.Variants {
		err = r.mountConfigMapToServicesPods(ctx, *mofaasFunc, labels, configMapName, policyExceptionName, policyName)
		if err != nil {
			log.Error(err, "Failed to mount ConfigMap", "service", service.Name)
			return err
		}
	}

	return nil
}

func (r *MoFaaSFunctionReconciler) mountConfigMapToServicesPods(ctx context.Context, mofaasFunc k8smofaascomv1.MoFaaSFunction, labels map[string]string, configMapName string, policyExceptionName string, policyName string) error {
	log := log.FromContext(ctx)

	namespace := mofaasFunc.Namespace
	/***************************************** CREATE POLICY EXCEPTION *****************************************/

	// Check if the PolicyException already exists
	existingPolicyException := &kyvernov2.PolicyException{}
	err := r.Client.Get(ctx, client.ObjectKey{
		Namespace: namespace,
		Name:      policyExceptionName,
	}, existingPolicyException)

	if err != nil && !apierrors.IsNotFound(err) {
		// Error occurred while fetching the existing PolicyException
		log.Error(err, "Failed to get existing PolicyException")
		return err
	}

	if err == nil {
		// PolicyException exists, no need to create
		log.Info("PolicyException already exists, skipping creation")
	} else {

		// Step 1: Load the YAML file for the Kyverno Policy Exception
		var policyException kyvernov2.PolicyException
		if err := loadYaml(kyvernoPolExceptPath, &policyException); err != nil {
			log.Error(err, "Failed to load Kyverno Policy Exception config")
			return err
		}

		// Modify it accordingly
		policyException.Name = policyExceptionName
		policyException.Namespace = namespace
		for key, value := range labels {
			policyException.Spec.Match.Any[0].ResourceDescription.Selector.MatchLabels[key] = value
		}

		if err := controllerutil.SetControllerReference(&mofaasFunc, &policyException, r.Scheme); err != nil {
			log.Error(err, "Error while setting controller reference for Policy Exception")
			return err
		}

		err = r.Client.Create(ctx, &policyException)
		if err != nil && !apierrors.IsAlreadyExists(err) {
			log.Error(err, "Failed to create Policy Exception")
			return err
		}
	}

	/***************************************** CREATE POLICY *****************************************/
	// Check if the Policy already exists
	existingPolicy := &kyvernov1.Policy{}
	err = r.Client.Get(ctx, client.ObjectKey{
		Namespace: namespace,
		Name:      policyName,
	}, existingPolicy)

	if err != nil && !apierrors.IsNotFound(err) {
		// Error occurred while fetching the existing Policy
		log.Error(err, "Failed to get existing Policy")
		return err
	}

	if err == nil {
		// Policy exists, no need to create
		log.Info("Policy already exists, skipping creation")
	} else {

		// Step 1: Load the YAML file for the Kyverno Policy Exception
		var policy kyvernov1.Policy
		if err := loadYaml(kyvernoPolPath, &policy); err != nil {
			log.Error(err, "Failed to load Kyverno Policy config")
			return err
		}

		// Modify it accordingly
		policy.Name = policyName
		policy.Namespace = namespace
		for key, value := range labels {
			policy.Spec.Rules[0].MatchResources.Any[0].ResourceDescription.Selector.MatchLabels[key] = value
		}

		var patch map[string]interface{}
		if policy.Spec.Rules[0].Mutation.RawPatchStrategicMerge != nil {
			if err := json.Unmarshal(policy.Spec.Rules[0].Mutation.RawPatchStrategicMerge.Raw, &patch); err != nil {
				log.Error(err, "Failed to unmarshal RawPatchStrategicMerge")
				return err
			}
		} else {
			patch = make(map[string]interface{})
		}

		// Ensure 'spec' exists
		spec, ok := patch["spec"].(map[string]interface{})
		if !ok {
			spec = make(map[string]interface{})
			patch["spec"] = spec
		}

		// Ensure 'volumes' exists
		volumes, ok := spec["volumes"].([]interface{})
		if !ok {
			volumes = []interface{}{}
		}
		volumeFound := false
		for i, v := range volumes {
			vol, _ := v.(map[string]interface{})
			if volName, _ := vol["name"].(string); volName == "envoy-config" {
				// Update existing volume
				vol["configMap"] = map[string]interface{}{"name": configMapName}
				volumes[i] = vol
				volumeFound = true
				break
			}
		}
		if !volumeFound {
			// Append new volume entry
			volumes = append(volumes, map[string]interface{}{
				"name": "envoy-config",
				"configMap": map[string]interface{}{
					"name": configMapName,
				},
			})
		}
		spec["volumes"] = volumes

		// Ensure "containers" exist
		containers, ok := spec["containers"].([]interface{})
		if !ok {
			containers = []interface{}{}
		}

		// Update or append the container volumeMount
		containerFound := false
		for i, c := range containers {
			container, _ := c.(map[string]interface{})
			if containerName, _ := container["name"].(string); containerName == "envoy" {
				// Ensure "volumeMounts" exist
				volumeMounts, ok := container["volumeMounts"].([]interface{})
				if !ok {
					volumeMounts = []interface{}{}
				}

				// Update or append the volumeMount
				volumeMountFound := false
				for j, vm := range volumeMounts {
					volMount, _ := vm.(map[string]interface{})
					if vmName, _ := volMount["name"].(string); vmName == "envoy-config" {
						volMount["mountPath"] = "/etc/envoy"
						volMount["readOnly"] = true
						volumeMounts[j] = volMount
						volumeMountFound = true
						break
					}
				}
				if !volumeMountFound {
					volumeMounts = append(volumeMounts, map[string]interface{}{
						"name":      "envoy-config",
						"mountPath": "/etc/envoy",
						"readOnly":  true,
					})
				}
				container["volumeMounts"] = volumeMounts
				containers[i] = container
				containerFound = true
				break
			}
		}
		if !containerFound {
			// Append new container entry
			containers = append(containers, map[string]interface{}{
				"name": "envoy",
				"volumeMounts": []interface{}{
					map[string]interface{}{
						"name":      "envoy-config",
						"mountPath": "/etc/envoy",
						"readOnly":  true,
					},
				},
			})
		}
		spec["containers"] = containers

		// Finally, marshal back to JSON and update policy
		patchBytes, err := json.Marshal(patch)
		if err != nil {
			log.Error(err, "Failed to marshal updated RawPatchStrategicMerge")
			return err
		}
		policy.Spec.Rules[0].Mutation.RawPatchStrategicMerge = &apiextv1.JSON{Raw: patchBytes}

		// policyWrapper := &k8smofaascomv1.PolicyWrapper{Policy: &policy}

		if err := controllerutil.SetControllerReference(&mofaasFunc, &policy, r.Scheme); err != nil {
			log.Error(err, "Error while setting controller reference for Policy")
			return err
		}

		err = r.Client.Create(ctx, &policy)
		if err != nil && !apierrors.IsAlreadyExists(err) {
			log.Error(err, "Failed to create Policy")
			return err
		}
	}

	return nil
}


func loadYaml(filePath string, config interface{}) error {
	data, err := os.ReadFile(filePath)
	if err != nil {
		return fmt.Errorf("failed to read yaml file: %w", err)
	}

	err = yaml.Unmarshal(data, config)
	if err != nil {
		return fmt.Errorf("failed to parse yaml file: %w", err)
	}

	return nil
}
