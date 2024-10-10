## Simple test

```bash
# The first two services is for http://developer.mozilla.org, the last one is for http://www.google.com
$ export SERVICES="aHR0cDovL2RldmVsb3Blci5tb3ppbGxhLm9yZw==,aHR0cDovL2RldmVsb3Blci5tb3ppbGxhLm9yZy8=,aHR0cDovL3d3dy5nb29nbGUuY29t" && export IGNORE_HEADERS="eC1ndXBsb2FkZXItdXBsb2FkaWQ=,WC1DbG91ZC1UcmFjZS1Db250ZXh0,RGF0ZQ==,RXhwaXJlcw==,QWdl,Q29udGVudC1MZW5ndGg=,QWx0LVN2Yw==" && export CONCURRENCY=2; python chooser.py
```
