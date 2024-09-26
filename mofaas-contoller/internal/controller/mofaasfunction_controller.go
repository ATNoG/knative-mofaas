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

	v1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	knativeServing "knative.dev/serving/pkg/apis/serving/v1"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
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
	_ = log.FromContext(ctx)

	// TODO(user): your logic here
	var mofaasFunc k8smofaascomv1.MoFaaSFunction
	if err := r.Get(ctx, req.NamespacedName, &mofaasFunc); err != nil {
		log.Log.Error(err, "Unable to fetch MoFaaSFunction")
		return ctrl.Result{}, client.IgnoreNotFound(err)
	}

	functionChooserService, err := r.createKnativeService(mofaasFunc)
	if err != nil {
		log.Log.Error(err, "Failed to create the Function Chooser Knative Service")
		return ctrl.Result{}, client.IgnoreNotFound(err)
	}

	if err := r.Create(ctx, &functionChooserService); err != nil {
		log.Log.Error(err, "Unable to create the Function Chooser Knative Service")
	}

	return ctrl.Result{}, nil
}

func (r *MoFaaSFunctionReconciler) createKnativeService(mofaasFunc k8smofaascomv1.MoFaaSFunction) (knativeServing.Service, error) {
	service := knativeServing.Service{
		TypeMeta: metav1.TypeMeta{APIVersion: knativeServing.Kind("Service").Group + "/v1", Kind: "Service"},
		ObjectMeta: metav1.ObjectMeta{
			Name:      "mofaas-chooser",
			Namespace: mofaasFunc.Namespace,
		},
		Spec: knativeServing.ServiceSpec{
			ConfigurationSpec: knativeServing.ConfigurationSpec{
				Template: knativeServing.RevisionTemplateSpec{
					Spec: knativeServing.RevisionSpec{
						PodSpec: v1.PodSpec{
							Containers: []v1.Container{
								{
									// Name:  "function-chooser",
									Image: "10.43.67.161:5000/function-chooser",
									Env: []v1.EnvVar{
										{
											Name:  "SERVICES",
											Value: "http://test.mofaas.svc.cluster.local",
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

// SetupWithManager sets up the controller with the Manager.
func (r *MoFaaSFunctionReconciler) SetupWithManager(mgr ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(mgr).
		For(&k8smofaascomv1.MoFaaSFunction{}).
		Complete(r)
}
