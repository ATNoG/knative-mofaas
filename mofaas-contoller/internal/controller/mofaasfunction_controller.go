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
	"fmt"
	"reflect"
	"strings"
	"time"

	core "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/api/meta"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
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
		if ok := controllerutil.AddFinalizer(&mofaasFunc, mofaasFunctionFinalizer); !ok {
			log.Error(nil, "Failed to add finalizer into the custom resource")
			return ctrl.Result{Requeue: true}, nil
		}

		if err := r.Update(ctx, &mofaasFunc); err != nil {
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
	functionChooserService, err := r.generateFuncChooserServiceStruct(ctx, mofaasFunc)
	if err != nil {
		log.Error(err, "Failed to create the Function Chooser Knative Service template")

		meta.SetStatusCondition(&mofaasFunc.Status.Conditions, metav1.Condition{
			Type:   typeAvailableMoFaaSFunction,
			Status: metav1.ConditionFalse, Reason: "Reconciling",
			Message: fmt.Sprintf("Failed to create Knative Serving for the custom resource (%s): (%s)", mofaasFunc.Name, err),
		})

		if err := r.Status().Update(ctx, &mofaasFunc); err != nil {
			log.Error(err, "Failed to update MoFaaSFunction status")
			return ctrl.Result{}, err
		}

		return ctrl.Result{}, err
	}

	/***************************************** CREATE OR UPDATE *****************************************/
	// Create or update the Knative Service for the Function Chooser
	// TODO - MAYBE IN THE FUTURE, WE SHOULD VERIFY IF THE SERVICE WAS CREATED COMPLETELY WITH SUCCESS (E.G., IT MIGHT FAIL IF THE CONTAINER IS NOT FOUND)
	currentService := serving.Service{}
	if err := r.Get(ctx, types.NamespacedName{Name: functionChooserService.Name, Namespace: req.Namespace}, &currentService); err != nil && apierrors.IsNotFound(err) {
		log.Info("Creating the new Function Chooser Knative Service")
		if err := r.Create(ctx, &functionChooserService); err != nil {
			log.Error(err, "Unable to create the Function Chooser Knative Service")
			return ctrl.Result{}, err
		}

		// Let's be sure we have the latest version
		if err := r.Get(ctx, req.NamespacedName, &mofaasFunc); err != nil {
			log.Error(err, "Failed to re-fetch MoFaaSFunction")
			return ctrl.Result{}, err
		}

		if err := r.updateStatusOnCreateOrUpdate(ctx, &mofaasFunc, functionChooserService); err != nil {
			log.Error(err, "Failed to update MoFaaSFunction status after Controller Knative Service creation")
			return ctrl.Result{}, err
		}
	} else if err != nil {
		log.Error(err, "Failed to get Knative Service")
		// Let's return the error for the reconciliation be re-trigged again
		return ctrl.Result{}, err
	} else { // There is no error, lets update!!!
		log.Info("Updating the Function Chooser Knative Service")

		// Let's be sure we have the latest version
		if err := r.Get(ctx, req.NamespacedName, &mofaasFunc); err != nil {
			log.Error(err, "Failed to re-fetch MoFaaSFunction")
			return ctrl.Result{}, err
		}

		updateStruct(&functionChooserService, currentService)
		if err := r.Update(ctx, &functionChooserService); err != nil {
			log.Error(err, "Unable to update the Function Chooser Knative Service")
			return ctrl.Result{}, err
		}

		// Let's be sure we have the latest version
		if err := r.Get(ctx, req.NamespacedName, &mofaasFunc); err != nil {
			log.Error(err, "Failed to re-fetch MoFaaSFunction")
			return ctrl.Result{}, err
		}

		if err := r.updateStatusOnCreateOrUpdate(ctx, &mofaasFunc, functionChooserService); err != nil {
			log.Error(err, "Failed to update MoFaaSFunction status after Controller Knative Service update")
			return ctrl.Result{}, err
		}
	}

	// Adapted from https://github.com/kubernetes-sigs/kubebuilder/blob/master/docs/book/src/getting-started/testdata/project/internal/controller/memcached_controller.go
	meta.SetStatusCondition(&mofaasFunc.Status.Conditions, metav1.Condition{
		Type:    typeAvailableMoFaaSFunction,
		Status:  metav1.ConditionTrue,
		Reason:  "Reconciling",
		Message: fmt.Sprintf("Knative Service for custom resource (%s) created successfully", mofaasFunc.Name),
	})
	if err := r.Status().Update(ctx, &mofaasFunc); err != nil {
		log.Error(err, "Failed to update MoFaaSFunction status")
		return ctrl.Result{}, err
	}

	return ctrl.Result{}, nil
}

func (r *MoFaaSFunctionReconciler) updateStatusOnCreateOrUpdate(ctx context.Context, mofaasFunc *k8smofaascomv1.MoFaaSFunction, controllerService serving.Service) error {
	log := log.FromContext(ctx)

	timeoutCtx, cancel := context.WithTimeout(context.Background(), time.Second*60) // TODO - MAYBE THIS SHOULD BE PASSED BY ARGUMENT
	defer cancel()
	for {
		// Let's be sure we have the latest version
		if err := r.Get(ctx, types.NamespacedName{Namespace: controllerService.Namespace, Name: controllerService.Name}, &controllerService); err != nil {
			log.Error(err, "Failed to re-fetch the MoFaaS Function Knative Service")
		}

		if controllerService.Status.Address != nil && controllerService.Status.URL != nil {
			mofaasFunc.Status.Address = controllerService.Status.Address.DeepCopy()
			mofaasFunc.Status.URL = controllerService.Status.URL.DeepCopy()
			break
		}

		select {
		case <-time.After(time.Second / 10): // Every 100 ms
		case <-timeoutCtx.Done():
			log.Error(timeoutCtx.Err(), "Error while waiting for the Knative Service address")
			return timeoutCtx.Err()
		}
	}
	mofaasFunc.Status.Controller = controllerService.Name

	if err := r.Status().Update(ctx, mofaasFunc); err != nil {
		log.Error(err, "Failed to update MoFaaSFunction status")
		return err
	}

	log.Info("Updated MoFaaSFunc Status with success after creation or update")

	return nil
}

func (r *MoFaaSFunctionReconciler) generateFuncChooserServiceStruct(ctx context.Context, mofaasFunc k8smofaascomv1.MoFaaSFunction) (serving.Service, error) {
	log := log.FromContext(ctx)

	// First, get the Knative Services' URLs MoFaaS has to protect
	srvURLs := make([]string, len(mofaasFunc.Spec.Variants))
	for i, variant := range mofaasFunc.Spec.Variants {
		kServiceName := variant.Name
		timeoutCtx, cancel := context.WithTimeout(context.Background(), time.Second*60) // TODO - MAYBE THIS SHOULD BE PASSED BY ARGUMENT
		defer cancel()

		for {
			srvObj, err := r.listObjectsByName(ctx, kServiceName, "mofaas")
			if err != nil {
				log.Error(err, "Error while listing services")
				return serving.Service{}, err
			}

			if srvObj.IsReady() {
				// log.Info(srvObj.Status.Address.URL.String())
				srvURLs[i] = srvObj.Status.Address.URL.String()
				break
			}

			select {
			case <-time.After(time.Second / 10): // Every 100 ms
			case <-timeoutCtx.Done():
				log.Error(timeoutCtx.Err(), "Error while waiting for the Knative Service "+srvObj.Name)
				return serving.Service{}, timeoutCtx.Err()
			}
		}

	}

	// Knative Service definition for the Function Chooser
	service := serving.Service{
		TypeMeta: metav1.TypeMeta{APIVersion: serving.Kind("Service").Group + "/v1", Kind: "Service"},
		ObjectMeta: metav1.ObjectMeta{
			Name:      "mofaas-chooser-" + mofaasFunc.Name,
			Namespace: mofaasFunc.Namespace,
		},
		Spec: serving.ServiceSpec{
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
											Value: strings.Join(srvURLs[:], ","),
										},
									},
								},
							},
						},
					},
				},
			},
		},
	}

	if err := ctrl.SetControllerReference(&mofaasFunc, &service, r.Scheme); err != nil {
		log.Error(err, "Error while setting controller reference")
		return serving.Service{}, err
	}

	return service, nil
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
