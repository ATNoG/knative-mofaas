package controller

import (
	kyvernov1 "github.com/kyverno/kyverno/api/kyverno/v1"
	kyvernov2 "github.com/kyverno/kyverno/api/kyverno/v2"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/runtime/schema"
)

/***************************************** Policy Exception *****************************************/
type PolicyExceptionWrapper struct {
	*kyvernov2.PolicyException
}

func (p *PolicyExceptionWrapper) GetObjectKind() schema.ObjectKind {
	return p
}

func (p *PolicyExceptionWrapper) DeepCopyObject() runtime.Object {
	return p.DeepCopy()
}

func (p *PolicyExceptionWrapper) GetObjectMeta() metav1.ObjectMeta {
	return p.ObjectMeta
}

/***************************************** Policy *****************************************/
type PolicyWrapper struct {
	*kyvernov1.Policy
}

func (p *PolicyWrapper) GetObjectKind() schema.ObjectKind {
	return p
}

func (p *PolicyWrapper) DeepCopyObject() runtime.Object {
	return p.DeepCopy()
}

func (p *PolicyWrapper) GetObjectMeta() metav1.ObjectMeta {
	return p.ObjectMeta
}
