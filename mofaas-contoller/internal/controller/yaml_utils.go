package controller

import (
	"fmt"
	"os"

	"gopkg.in/yaml.v3"
)

func loadYaml(filePath string, config interface{}) error {
	data, err := os.ReadFile(filePath)
	if err != nil {
		return fmt.Errorf("failed to read envoy.yaml: %w", err)
	}

	err = yaml.Unmarshal(data, &config)
	if err != nil {
		return fmt.Errorf("failed to parse envoy.yaml: %w", err)
	}

	return nil
}
