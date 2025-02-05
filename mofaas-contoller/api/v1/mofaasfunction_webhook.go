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

package v1

import (
	"fmt"
	"reflect"

	"k8s.io/apimachinery/pkg/runtime"
	ctrl "sigs.k8s.io/controller-runtime"
	logf "sigs.k8s.io/controller-runtime/pkg/log"
	"sigs.k8s.io/controller-runtime/pkg/webhook"
	"sigs.k8s.io/controller-runtime/pkg/webhook/admission"
)

type immutableFieldInfo struct {
	newField any
	oldField any
	fieldName string
}

// log is for logging in this package.
var mofaasfunctionlog = logf.Log.WithName("mofaasfunction-resource")

// SetupWebhookWithManager will setup the manager to manage the webhooks
func (r *MoFaaSFunction) SetupWebhookWithManager(mgr ctrl.Manager) error {
	return ctrl.NewWebhookManagedBy(mgr).
		For(r).
		Complete()
}

// TODO(user): EDIT THIS FILE!  THIS IS SCAFFOLDING FOR YOU TO OWN!

// TODO(user): change verbs to "verbs=create;update;delete" if you want to enable deletion validation.
// NOTE: The 'path' attribute must follow a specific pattern and should not be modified directly here.
// Modifying the path for an invalid path can cause API server errors; failing to locate the webhook.
// +kubebuilder:webhook:path=/validate-mofaas-atnog-v1-mofaasfunction,mutating=false,failurePolicy=fail,sideEffects=None,groups=mofaas.atnog,resources=mofaasfunctions,verbs=create;update,versions=v1,name=vmofaasfunction.kb.io,admissionReviewVersions=v1

var _ webhook.Validator = &MoFaaSFunction{}

// ValidateCreate implements webhook.Validator so a webhook will be registered for the type
func (r *MoFaaSFunction) ValidateCreate() (admission.Warnings, error) {
	mofaasfunctionlog.Info("validate create", "name", r.Name)

	return r.validateConcurrency()
	// return nil, nil
}

// ValidateUpdate implements webhook.Validator so a webhook will be registered for the type
func (r *MoFaaSFunction) ValidateUpdate(old runtime.Object) (admission.Warnings, error) {
	mofaasfunctionlog.Info("validate update", "name", r.Name)

	if oldFunction, ok := old.(*MoFaaSFunction); !ok {
		return nil, fmt.Errorf("error casting old object to MoFaaSFunction")
	} else {
		immutableFields := [...]immutableFieldInfo{
			{
				newField: r.TypeMeta,
				oldField: oldFunction.TypeMeta,
				fieldName: "Kind and apiVersion",
			},
			{
				newField: r.ObjectMeta.Name,
				oldField: oldFunction.ObjectMeta.Name,
				fieldName: "Name",
			},
			{
				newField: r.ObjectMeta.Namespace,
				oldField: oldFunction.ObjectMeta.Namespace,
				fieldName: "Namespace",
			},
			{
				newField: r.ObjectMeta.UID,
				oldField: oldFunction.ObjectMeta.UID,
				fieldName: "UID",
			},			
			// {
			// 	newField: r.Status,
			// 	oldField: oldFunction.Status,
			// 	fieldName: "Status",
			// },
		}

		for _, f := range immutableFields {
			if err := r.validateImmutable(f); err != nil {
				return nil, err
			}
		}
	}
	return r.validateConcurrency()
	
	// return nil, nil
}

// ValidateDelete implements webhook.Validator so a webhook will be registered for the type
func (r *MoFaaSFunction) ValidateDelete() (admission.Warnings, error) {
	mofaasfunctionlog.Info("validate delete", "name", r.Name)

	// TODO(user): fill in your validation logic upon object deletion.
	return nil, nil
}

func (r *MoFaaSFunction) validateConcurrency() (admission.Warnings, error) {
	if r.Spec.Concurrency > len(r.Spec.Variants) {
		return nil, fmt.Errorf("spec.concurrency cannot be greater than the length of spec.variants, which is %d", len(r.Spec.Variants))
	}
	return nil, nil
}

func (r *MoFaaSFunction) validateImmutable(fieldInfo immutableFieldInfo) (error) {
	if !reflect.DeepEqual(fieldInfo.newField, fieldInfo.oldField) {
		return fmt.Errorf("%s is immutable", fieldInfo.fieldName)
	}
	return nil
}
