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
	"reflect"
	"strconv"
	"strings"
	"time"

	core "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	serving "knative.dev/serving/pkg/apis/serving/v1"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/client/config"
	"sigs.k8s.io/controller-runtime/pkg/log"

	k8smofaascomv1 "mofaas/api/v1"
)

// MoFaaSFunctionReconciler reconciles a MoFaaSFunction object
type MoFaaSFunctionReconciler struct {
	client.Client
	Scheme *runtime.Scheme
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

	// mofaasFunc.Status
	functionChooserService, err := r.createKnativeService(ctx, mofaasFunc)
	if err != nil {
		log.Error(err, "Failed to create the Function Chooser Knative Service")
		return ctrl.Result{}, err
	}

	currentService := serving.Service{}
	if err := r.Get(ctx, types.NamespacedName{Name: functionChooserService.Name, Namespace: req.Namespace}, &currentService); err != nil && apierrors.IsNotFound(err) {
		if err := r.Create(ctx, &functionChooserService); err != nil {
			log.Error(err, "Unable to create the Function Chooser Knative Service")
			return ctrl.Result{}, err
		}
	} else if err != nil {
		log.Error(err, "Failed to get Knative Service")
		// Let's return the error for the reconciliation be re-trigged again
		return ctrl.Result{}, err
	} else { // There is no error, lets update!!!
		log.Info("Updating the Function Chooser Knative Service")
		// functionChooserService.SetResourceVersion(currentService.GetResourceVersion())
		updateStruct(&functionChooserService, currentService)
		if err := r.Update(ctx, &functionChooserService); err != nil {
			log.Error(err, "Unable to update the Function Chooser Knative Service")
			return ctrl.Result{}, err
		}
	}

	return ctrl.Result{}, nil
}

func (r *MoFaaSFunctionReconciler) createKnativeService(ctx context.Context, mofaasFunc k8smofaascomv1.MoFaaSFunction) (serving.Service, error) {
	// First, get the Knative Services' URLs MoFaaS has to protect
	srvURLs := make([]string, len(mofaasFunc.Spec.Variants))
	for i, variant := range mofaasFunc.Spec.Variants {
		kServiceName := variant.Name
		// kServiceNamespace := variant.Namespace
		// srvObj, err := r.listObjectsByName(ctx, "", kServiceName, "mofaas")
		// if err != nil {
		// 	log.Log.Error(err, "Error while listing services")
		// 	return serving.Service{}, err
		// }
		// log.Log.Info(strconv.Itoa(i))
		timeoutCtx, cancel := context.WithTimeout(context.Background(), time.Second*60)
		defer cancel()

		for {
			srvObj, err := r.listObjectsByName(ctx, "", kServiceName, "mofaas")
			if err != nil {
				log.Log.Error(err, "Error while listing services")
				return serving.Service{}, err
			}
			log.Log.Info(strconv.Itoa(i))

			if srvObj.IsReady() {
				log.Log.Info(srvObj.Status.Address.URL.String())
				srvURLs[i] = srvObj.Status.Address.URL.String()
				break
			}

			select {
			case <-time.After(time.Second / 10):
			case <-timeoutCtx.Done():
				log.Log.Error(timeoutCtx.Err(), "Error while waiting for the Knative Service "+srvObj.Name)
				return serving.Service{}, timeoutCtx.Err()
			}
		}

	}
	log.Log.Info(strings.Join(srvURLs[:], ","))

	service := serving.Service{
		TypeMeta: metav1.TypeMeta{APIVersion: serving.Kind("Service").Group + "/v1", Kind: "Service"},
		ObjectMeta: metav1.ObjectMeta{
			Name:      "mofaas-chooser",
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
									Image: "10.43.67.161:5000/function-chooser",
									Env: []core.EnvVar{
										{
											Name:  "SERVICES",
											Value: strings.Join(srvURLs[:], ","), // "http://test.mofaas.svc.cluster.local",
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

	return service, nil
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

/*
WITH THE HELP OF ChatGPT
*/
func (r *MoFaaSFunctionReconciler) listObjectsByName(ctx context.Context, kind, name, namespace string) (serving.Service, error) {
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

// SetupWithManager sets up the controller with the Manager.
func (r *MoFaaSFunctionReconciler) SetupWithManager(mgr ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(mgr).
		For(&k8smofaascomv1.MoFaaSFunction{}).
		Complete(r)
}
