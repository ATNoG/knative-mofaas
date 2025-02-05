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
	"fmt"
	"reflect"
	"strconv"
	"strings"
	"time"

	core "k8s.io/api/core/v1"
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
	functionChooserService := serving.Service{
		TypeMeta: metav1.TypeMeta{
			APIVersion: serving.Kind("Service").Group + "/v1", Kind: "Service",
		},
		ObjectMeta: metav1.ObjectMeta{
			Name:      "mofaas-chooser-" + mofaasFunc.Name,
			Namespace: mofaasFunc.Namespace,
		},
	}
	egressProxyService := serving.Service{
		TypeMeta: metav1.TypeMeta{
			APIVersion: serving.Kind("Service").Group + "/v1", Kind: "Service",
		},
		ObjectMeta: metav1.ObjectMeta{
			Name:      "mofaas-egress-proxy-" + mofaasFunc.Name,
			Namespace: mofaasFunc.Namespace,
		},
	}

	/***************************************** CREATE OR UPDATE *****************************************/
	// Create or update the Knative Service for the Function Chooser
	// TODO - MAYBE IN THE FUTURE, WE SHOULD VERIFY IF THE SERVICE WAS CREATED COMPLETELY WITH SUCCESS (E.G., IT MIGHT FAIL IF THE CONTAINER IS NOT FOUND)
	result, err := controllerutil.CreateOrUpdate(ctx, r.Client, &functionChooserService, func() error {
		err := r.generateFuncChooserServiceStruct(ctx, mofaasFunc, &functionChooserService)
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

	_, err = controllerutil.CreateOrUpdate(ctx, r.Client, &egressProxyService, func() error {
		err := r.generateEgressProxyServiceStruct(ctx, mofaasFunc, &egressProxyService)
		return err
	})
	if err != nil {
		log.Error(err, "Unable to update or create the Egress Proxy Service")
		return ctrl.Result{}, err
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
				Spec: serving.RevisionSpec{
					PodSpec: core.PodSpec{
						Containers: []core.Container{
							{
								// Name:  "function-chooser",
								Image: r.EgressProxyImage,
								Env: []core.EnvVar{
									{
										Name:  "CONCURRENCY",
										Value: strconv.Itoa(mofaasFunc.Spec.Concurrency),
									},
								},
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

func (r *MoFaaSFunctionReconciler) generateFuncChooserServiceStruct(ctx context.Context, mofaasFunc k8smofaascomv1.MoFaaSFunction, functionChooserService *serving.Service) error {
	log := log.FromContext(ctx)

	// First, get the headers to ignore
	ignoreHeadersEnc := make([]string, len(mofaasFunc.Spec.DeepCopy().IgnoreHeaders))
	for i, header := range mofaasFunc.Spec.IgnoreHeaders {
		ignoreHeadersEnc[i] = base64.StdEncoding.EncodeToString([]byte(header))
	}

	// Second, get the Knative Services' URLs MoFaaS has to protect
	srvEncURLs := make([]string, len(mofaasFunc.Spec.Variants))
	for i, variant := range mofaasFunc.Spec.Variants {
		kServiceName := variant.Name
		timeoutCtx, cancel := context.WithTimeout(context.Background(), time.Second*60) // TODO - MAYBE THIS SHOULD BE PASSED BY ARGUMENT
		defer cancel()

		for {
			srvObj, err := r.listObjectsByName(ctx, kServiceName, "mofaas")
			if err != nil {
				log.Error(err, "Error while listing services")
				return err
			}

			if srvObj.IsReady() {
				// log.Info(srvObj.Status.Address.URL.String())
				currentUrl := srvObj.Status.Address.URL.String()
				srvEncURLs[i] = base64.StdEncoding.EncodeToString([]byte(currentUrl))
				break
			}

			select {
			case <-time.After(time.Second / 10): // Every 100 ms
			case <-timeoutCtx.Done():
				log.Error(timeoutCtx.Err(), "Error while waiting for the Knative Service "+srvObj.Name)
				return timeoutCtx.Err()
			}
		}

	}

	// Knative Service definition for the Function Chooser
	// functionChooserService.TypeMeta = metav1.TypeMeta{APIVersion: serving.Kind("Service").Group + "/v1", Kind: "Service"}
	// functionChooserService.ObjectMeta.Name = "mofaas-chooser-" + mofaasFunc.Name
	// functionChooserService.ObjectMeta.Namespace = mofaasFunc.Namespace
	functionChooserService.Spec = serving.ServiceSpec{
		ConfigurationSpec: serving.ConfigurationSpec{
			Template: serving.RevisionTemplateSpec{
				Spec: serving.RevisionSpec{
					PodSpec: core.PodSpec{
						Containers: []core.Container{
							{
								// Name:  "function-chooser",
								Image: r.FunctionChooserImage,
								Env: []core.EnvVar{
									{
										Name:  "SERVICES",
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

	if err := ctrl.SetControllerReference(&mofaasFunc, functionChooserService, r.Scheme); err != nil {
		log.Error(err, "Error while setting controller reference for Function Chooser")
		return err
	}

	return nil
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
