package controller

import (
	"fmt"
	"strings"
)

func updateEnvoyAddress(config map[string]interface{}, newAddress string) error {
	// Navigate dynamically to the address field
	staticResources, ok := config["static_resources"].(map[string]interface{})
	if !ok {
		return fmt.Errorf("missing static_resources")
	}

	clusters, ok := staticResources["clusters"].([]interface{})
	if !ok || len(clusters) == 0 {
		return fmt.Errorf("missing clusters")
	}

	// Find the "firewall_cluster"
	for _, c := range clusters {
		cluster, ok := c.(map[string]interface{})
		if !ok {
			continue
		}

		if cluster["name"] == "firewall_cluster" {
			loadAssignment, ok := cluster["load_assignment"].(map[string]interface{})
			if !ok {
				return fmt.Errorf("missing load_assignment")
			}

			endpoints, ok := loadAssignment["endpoints"].([]interface{})
			if !ok || len(endpoints) == 0 {
				return fmt.Errorf("missing endpoints")
			}

			lbEndpoints, ok := endpoints[0].(map[string]interface{})["lb_endpoints"].([]interface{})
			if !ok || len(lbEndpoints) == 0 {
				return fmt.Errorf("missing lb_endpoints")
			}

			endpoint, ok := lbEndpoints[0].(map[string]interface{})["endpoint"].(map[string]interface{})
			if !ok {
				return fmt.Errorf("missing endpoint")
			}

			address, ok := endpoint["address"].(map[string]interface{})
			if !ok {
				return fmt.Errorf("missing address")
			}

			socketAddress, ok := address["socket_address"].(map[string]interface{})
			if !ok {
				return fmt.Errorf("missing socket_address")
			}

			// Update the address dynamically
			newAddress = strings.TrimPrefix(newAddress, "http://")
			newAddress = strings.TrimPrefix(newAddress, "https://")
			socketAddress["address"] = newAddress
			return nil
		}
	}

	return fmt.Errorf("firewall_cluster not found")
}
