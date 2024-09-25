# knative-mofaas

## To create the skeleton for the Controller
```bash
$ go mod init k8s.mofaas.com
$ kubebuilder init
$ kubebuilder create api --group k8s.mofaas.com --version v1 --kind MoFaaSFunction

$ go get knative.dev/serving/pkg/apis/serving/v1
```