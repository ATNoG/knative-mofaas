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
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"knative.dev/pkg/apis"
	duckv1 "knative.dev/pkg/apis/duck/v1"
)

// EDIT THIS FILE!  THIS IS SCAFFOLDING FOR YOU TO OWN!
// NOTE: json tags are required.  Any new fields you add must have json tags for the fields to be serialized.

// MoFaaSFunctionSpec defines the desired state of MoFaaSFunction
type MoFaaSFunctionSpec struct {
	// Concurrenty will default to 1 if not defined
	// +default=1
	Concurrency int `json:"concurrency,omitempty" validation:"Maximum({.spec.variants | len})"`

	// +default=false
	Private bool `json:"private,omitempty"`

	Variants []VariantSpec `json:"variants,omitempty"`

	// IgnoreHeaders will default to an empty array if not given
	// +default=[]
	IgnoreHeaders []string `json:"ignore-headers,omitempty"`
}

type VariantSpec struct {
	Kind       string `json:"kind" immutable:"true"`
	Name       string `json:"name" immutable:"true"`
	APIVersion string `json:"apiVersion,omitempty"`
}

// MoFaaSFunctionStatus defines the observed state of MoFaaSFunction
type MoFaaSFunctionStatus struct {
	// INSERT ADDITIONAL STATUS FIELD - define observed state of cluster
	// Important: Run "make" to regenerate code after modifying this file

	Conditions []metav1.Condition `json:"conditions,omitempty" patchStrategy:"merge" patchMergeKey:"type" protobuf:"bytes,1,rep,name=conditions"`

	// Name of the Knative Service for the MoFaaS Controller
	Controller string `json:"controller"`

	// From Knative Serving (it will be similar to it)
	// Address holds the information needed for a Route to be the target of an event.
	// +optional
	Address *duckv1.Addressable `json:"address,omitempty"`
	// URL holds the url that will distribute traffic over the provided traffic targets.
	// It generally has the form http[s]://{route-name}.{route-namespace}.{cluster-level-suffix}
	// +optional
	URL *apis.URL `json:"url,omitempty"`
}

// +kubebuilder:object:root=true
// +kubebuilder:subresource:status
// +kubebuilder:resource:shortName={mofaas, mofaasfunc}
// +kubebuilder:printcolumn:name="URL",type="string",JSONPath=`.status.url`
// +kubebuilder:printcolumn:name="Knative Service Controller",type="string",JSONPath=`.status.controller`
// +kubebuilder:printcolumn:name="Age",type="date",JSONPath=`.metadata.creationTimestamp`

// MoFaaSFunction is the Schema for the mofaasfunctions API
type MoFaaSFunction struct {
	metav1.TypeMeta   `json:",inline"`
	metav1.ObjectMeta `json:"metadata,omitempty"`

	Spec   MoFaaSFunctionSpec   `json:"spec,omitempty"`
	Status MoFaaSFunctionStatus `json:"status,omitempty"`
}

// +kubebuilder:object:root=true

// MoFaaSFunctionList contains a list of MoFaaSFunction
type MoFaaSFunctionList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitempty"`
	Items           []MoFaaSFunction `json:"items"`
}

func init() {
	SchemeBuilder.Register(&MoFaaSFunction{}, &MoFaaSFunctionList{})
}
