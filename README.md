# knative-mofaas

## To create the skeleton for the Controller
```bash
$ go mod init mofaas
$ kubebuilder init
$ kubebuilder create api --group mofaas --domain atnog --version v1 --kind MoFaaSFunction

$ go get knative.dev/serving/pkg/apis/serving/v1
```