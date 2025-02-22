package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/url"
	"os"
	"strings"

	"github.com/golang-jwt/jwt/v5"
	"github.com/valyala/fasthttp"
)

var (
	headersRemove = map[string]struct{}{
		"ce-id":          {},
		"ce-specversion": {},
		"ce-type":        {},
		"ce-source":      {},
		"content-type":   {},
		"host":           {},
		"x-k-sink":       {},
	}
	secretKey = os.Getenv("SECRET_KEY")
	kSink     = os.Getenv("K_SINK")
)

func main() {
	if secretKey == "" {
		log.Fatal("Missing required environment variable: SECRET_KEY")
	}

	server := fasthttp.Server{
		Handler: requestHandler,
	}

	log.Println("Server listening on port 8080...")
	if err := server.ListenAndServe(":8080"); err != nil {
		log.Fatalf("Error starting server: %v", err)
	}
}

func requestHandler(ctx *fasthttp.RequestCtx) {
	authHeader := string(ctx.Request.Header.Peek("Authorization"))
	if !strings.HasPrefix(strings.ToLower(authHeader), "bearer ") {
		forwardToBroker(ctx, nil, "Missing or invalid token", 401)
		return
	}
	tokenStr := authHeader[7:]
	
	claims := jwt.MapClaims{}
	token, err := jwt.ParseWithClaims(tokenStr, claims, func(token *jwt.Token) (interface{}, error) {
		return []byte(secretKey), nil
	})

	if err != nil || !token.Valid {
		forwardToBroker(ctx, nil, "Invalid token", 401)
		return
	}

	client, _ := claims["sub"].(string)
	hasAccess, _ := claims["has_access"].(bool)
	if !hasAccess {
		forwardToBroker(ctx, &client, "Access denied", 403)
	} else {
		forwardToBroker(ctx, &client, "Forwarded", 200)
	}
}

func forwardToBroker(ctx *fasthttp.RequestCtx, client *string, message string, statusCode int) {
	proceed := (statusCode == 200)
	
	var payload map[string]interface{}
	if err := json.Unmarshal(ctx.Request.Body(), &payload); err != nil {
		payload = make(map[string]interface{})
	}

	payload["client"] = client
	payload["message"] = message
	
	outHeaders := make(map[string]string)
	ctx.Request.Header.VisitAll(func(key, value []byte) {
		k := strings.ToLower(string(key))
		if _, exists := headersRemove[k]; !exists {
			outHeaders[string(key)] = string(value)
		}
	})

	if ceID := ctx.Request.Header.Peek("Ce-Id"); len(ceID) > 0 {
		outHeaders["Ce-Id"] = string(ceID)
	}
	outHeaders["Ce-Specversion"] = "1.0"
	outHeaders["Ce-Type"] = "authorization"
	outHeaders["Ce-Source"] = "authorization"
	outHeaders["Content-Type"] = "application/json"
	outHeaders["Ce-dv"] = fmt.Sprintf("%t", proceed)

	targetSink := string(ctx.Request.Header.Peek("X-K-Sink"))
	if targetSink == "" {
		targetSink = kSink
	}

	if targetSink != "" {
		parsedURL, err := url.Parse(targetSink)
		if err == nil && parsedURL.Host != "" {
			forwardEvent(parsedURL, outHeaders, payload)
		} else {
			log.Println("Warning: No valid sink configured. Event not forwarded.")
		}
	}

	ctx.SetStatusCode(statusCode)
	ctx.Response.Header.Set("Content-Type", "application/json")
	responseBody, _ := json.Marshal(map[string]string{"message": message})
	ctx.Write(responseBody)
}

func forwardEvent(parsedURL *url.URL, headers map[string]string, payload map[string]interface{}) {
	path := parsedURL.Path
	if path == "" {
		path = "/"
	}

	body, _ := json.Marshal(payload)
	
	r := fasthttp.AcquireRequest()
	r.SetRequestURI(parsedURL.String())
	r.Header.SetMethod("POST")
	for k, v := range headers {
		r.Header.Set(k, v)
	}
	r.SetBody(body)

	resp := fasthttp.AcquireResponse()
	err := fasthttp.Do(r, resp)
	if err != nil {
		log.Printf("Failed to forward event to %s: %v", parsedURL.String(), err)
	} else {
		log.Printf("Successfully forwarded event to: %s. Response: %s", parsedURL.String(), resp.Body())
	}

	fasthttp.ReleaseRequest(r)
	fasthttp.ReleaseResponse(resp)
}
