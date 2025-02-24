package main

import (
	"encoding/json"
	"fmt"
	"io/ioutil"
	"log"
	"net/http"
	"os"
	"strconv"
	"strings"
)

// Environment variables
var (
	DIRECTUS_URL   = os.Getenv("DIRECTUS_URL")
	DIRECTUS_TOKEN = os.Getenv("DIRECTUS_TOKEN")
	K_SINK         = os.Getenv("K_SINK")
	OTP_SECRET     = os.Getenv("OTP_SECRET")
	MAX_AMOUNT     float64
)

// Headers to remove from the incoming request when forwarding.
var HEADERS_REMOVE = []string{
	"ce-id", "ce-specversion", "ce-type", "ce-source", "content-type", "host", "x-k-sink",
}

// TransactionPayload is a generic map to hold incoming JSON data.
type TransactionPayload map[string]interface{}

func main() {
	// Ensure required environment variables exist and parse MAX_AMOUNT
	if DIRECTUS_URL == "" || DIRECTUS_TOKEN == "" || OTP_SECRET == "" {
		log.Fatal("Missing required environment variables: DIRECTUS_URL, DIRECTUS_TOKEN, OTP_SECRET")
	}
	maxAmountStr := os.Getenv("MAX_AMOUNT")
	if maxAmountStr == "" {
		log.Fatal("Missing required environment variable: MAX_AMOUNT")
	}
	var err error
	MAX_AMOUNT, err = strconv.ParseFloat(maxAmountStr, 64)
	if err != nil || MAX_AMOUNT == 0 {
		log.Fatal("Invalid MAX_AMOUNT")
	}
	if K_SINK == "" {
		log.Println("Warning: K_SINK is not set. Events will not be forwarded.")
	}

	http.HandleFunc("/", handler)
	log.Println("Server started on port 8080")
	log.Fatal(http.ListenAndServe(":8080", nil))
}

func handler(w http.ResponseWriter, r *http.Request) {
	// Only allow POST requests
	if r.Method != http.MethodPost {
		w.WriteHeader(http.StatusMethodNotAllowed)
		json.NewEncoder(w).Encode(map[string]string{"message": "Method Not Allowed"})
		return
	}

	// Read and parse the JSON body
	bodyBytes, err := ioutil.ReadAll(r.Body)
	if err != nil {
		respond(w, http.StatusBadRequest, "Invalid JSON")
		return
	}
	defer r.Body.Close()

	var body TransactionPayload
	if err := json.Unmarshal(bodyBytes, &body); err != nil {
		respond(w, http.StatusBadRequest, "Invalid JSON")
		return
	}

	// Initialize state variables
	proceed := true
	message := "Forwarded"
	statusCode := 200

	// Parse and validate "amount"
	var amount float64
	if amt, ok := body["amount"]; ok {
		switch v := amt.(type) {
		case float64:
			amount = v
		case string:
			// Trim and parse
			v = strings.TrimSpace(v)
			amount, err = strconv.ParseFloat(v, 64)
			if err != nil {
				proceed = false
				message = "Invalid amount provided"
				statusCode = 400
			}
		default:
			proceed = false
			message = "Invalid amount provided"
			statusCode = 400
		}
	} else {
		proceed = false
		message = "Invalid amount provided"
		statusCode = 400
	}

	// Retrieve client usernames and OTP from the payload
	clientUsername, _ := body["client"].(string)
	destinationClient, _ := body["destination_client"].(string)
	var otp string
	if val, ok := body["otp"]; ok {
		otp = fmt.Sprintf("%v", val)
	}
	// Cast OTP_SECRET to string
	otpSecret := fmt.Sprintf("%v", OTP_SECRET)

	// Check OTP if amount exceeds MAX_AMOUNT
	if statusCode == 200 && amount > MAX_AMOUNT && (otp == "" || otp != otpSecret) {
		proceed = false
		message = "OTP required or incorrect"
		statusCode = 403
	}

	// Get the request id from the headers (if any)
	reqID := r.Header.Get("Ce-Id")

	// Retrieve user IDs sequentially:
	fromID := getUserId(clientUsername, reqID)
	toID := getUserId(destinationClient, reqID)
	if statusCode == 200 && (fromID == nil || toID == nil) {
		proceed = false
		message = "Invalid client usernames"
		statusCode = 400
	}

	// Build payload: copy original payload and add extra fields
	body["message"] = message
	if fromID != nil {
		body["from"] = *fromID
	} else {
		body["from"] = nil
	}
	if toID != nil {
		body["to"] = *toID
	} else {
		body["to"] = nil
	}

	// Forward to broker
	forwardToBroker(r, body, proceed, message, statusCode)

	// Respond to the original requester
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(statusCode)
	json.NewEncoder(w).Encode(map[string]string{"message": message})
}

// getUserId makes a synchronous HTTP GET request to Directus to retrieve the user ID for a given username.
func getUserId(username, reqID string) *int {
	if username == "" {
		return nil
	}
	url := fmt.Sprintf("%s/items/users?filter[username][_eq]=%s", DIRECTUS_URL, username)
	client := &http.Client{}
	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		return nil
	}
	req.Header.Set("Authorization", "Bearer "+DIRECTUS_TOKEN)
	req.Header.Set("Ce-Id", reqID)

	resp, err := client.Do(req)
	if err != nil {
		return nil
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil
	}
	bodyBytes, err := ioutil.ReadAll(resp.Body)
	if err != nil {
		return nil
	}
	// Expected JSON format: { "data": [ { "id": <number> } ] }
	var result struct {
		Data []struct {
			ID int `json:"id"`
		} `json:"data"`
	}
	if err := json.Unmarshal(bodyBytes, &result); err != nil {
		return nil
	}
	if len(result.Data) > 0 {
		return &result.Data[0].ID
	}
	return nil
}

// forwardToBroker forwards the payload to the external broker (sink) with adjusted headers.
func forwardToBroker(r *http.Request, payload TransactionPayload, proceed bool, message string, statusCode int) {
	// Determine target sink from header or environment variable.
	targetSink := r.Header.Get("X-K-Sink")
	if targetSink == "" {
		targetSink = K_SINK
	}

	// Build headers: copy allowed headers from the incoming request.
	headers := make(map[string]string)
	for key, values := range r.Header {
		lowerKey := strings.ToLower(key)
		skip := false
		for _, removeKey := range HEADERS_REMOVE {
			if lowerKey == removeKey {
				skip = true
				break
			}
		}
		if !skip && len(values) > 0 {
			headers[key] = values[0]
		}
	}
	// Set additional fixed headers.
	headers["Ce-Id"] = r.Header.Get("Ce-Id")
	headers["Ce-Specversion"] = "1.0"
	headers["Ce-Type"] = "transaction"
	headers["Ce-Source"] = "verify-transaction"
	if proceed {
		headers["Ce-Dt"] = "true"
	} else {
		headers["Ce-Dt"] = "false"
	}
	headers["Content-Type"] = "application/json"

	if targetSink != "" {
		jsonPayload, err := json.Marshal(payload)
		if err != nil {
			log.Println("Error marshalling payload:", err)
			return
		}
		client := &http.Client{}
		req, err := http.NewRequest("POST", targetSink, strings.NewReader(string(jsonPayload)))
		if err != nil {
			log.Println("Error creating request to broker:", err)
			return
		}
		// Set headers on the outgoing request.
		for k, v := range headers {
			req.Header.Set(k, v)
		}
		resp, err := client.Do(req)
		if err != nil {
			log.Println("Failed to forward event:", err)
		} else {
			defer resp.Body.Close()
			log.Println("Successfully forwarded event, status code:", resp.StatusCode)
		}
	} else {
		log.Println("Warning: No valid sink configured. Event not forwarded.")
	}
}

func respond(w http.ResponseWriter, code int, message string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	json.NewEncoder(w).Encode(map[string]string{"message": message})
}
