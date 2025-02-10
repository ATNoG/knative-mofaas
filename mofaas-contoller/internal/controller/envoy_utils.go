package controller

import (
	"fmt"
	"strings"
)

func updateEnvoyAddress(config map[string]interface{}, newAddress string) error {
	// Normalize the new address
	newAddress = strings.TrimPrefix(newAddress, "http://")
	newAddress = strings.TrimPrefix(newAddress, "https://")

	// Navigate to static_resources
	staticResources, ok := config["static_resources"].(map[string]interface{})
	if !ok {
		return fmt.Errorf("missing static_resources")
	}

	// Update clusters -> firewall_cluster -> address
	clusters, ok := staticResources["clusters"].([]interface{})
	if !ok || len(clusters) == 0 {
		return fmt.Errorf("missing clusters")
	}

	firewallUpdated := false
	for _, c := range clusters {
		cluster, ok := c.(map[string]interface{})
		if !ok || cluster["name"] != "firewall_cluster" {
			continue
		}

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

		// Update the address
		socketAddress["address"] = newAddress
		firewallUpdated = true
		break
	}

	if !firewallUpdated {
		return fmt.Errorf("firewall_cluster not found")
	}

	// Update host_rewrite_literal in route_config
	listeners, ok := staticResources["listeners"].([]interface{})
	if !ok || len(listeners) == 0 {
		return fmt.Errorf("missing listeners")
	}

	routeUpdated := false
	for _, l := range listeners {
		listener, ok := l.(map[string]interface{})
		if !ok {
			continue
		}

		filterChains, ok := listener["filter_chains"].([]interface{})
		if !ok || len(filterChains) == 0 {
			continue
		}

		for _, fc := range filterChains {
			filterChain, ok := fc.(map[string]interface{})
			if !ok {
				continue
			}

			filters, ok := filterChain["filters"].([]interface{})
			if !ok || len(filters) == 0 {
				continue
			}

			for _, f := range filters {
				filter, ok := f.(map[string]interface{})
				if !ok {
					continue
				}

				if filter["name"] == "envoy.filters.network.http_connection_manager" {
					typedConfig, ok := filter["typed_config"].(map[string]interface{})
					if !ok {
						return fmt.Errorf("missing typed_config")
					}

					routeConfig, ok := typedConfig["route_config"].(map[string]interface{})
					if !ok {
						return fmt.Errorf("missing route_config")
					}

					virtualHosts, ok := routeConfig["virtual_hosts"].([]interface{})
					if !ok || len(virtualHosts) == 0 {
						return fmt.Errorf("missing virtual_hosts")
					}

					for _, vh := range virtualHosts {
						virtualHost, ok := vh.(map[string]interface{})
						if !ok {
							continue
						}

						routes, ok := virtualHost["routes"].([]interface{})
						if !ok || len(routes) == 0 {
							continue
						}

						for _, r := range routes {
							route, ok := r.(map[string]interface{})
							if !ok {
								continue
							}

							routeAction, ok := route["route"].(map[string]interface{})
							if !ok {
								continue
							}

							// Update host_rewrite_literal
							routeAction["host_rewrite_literal"] = newAddress
							routeUpdated = true
							break
						}
					}
				}
			}
		}
	}

	if !routeUpdated {
		return fmt.Errorf("host_rewrite_literal not found in route configuration")
	}

	return nil
}
