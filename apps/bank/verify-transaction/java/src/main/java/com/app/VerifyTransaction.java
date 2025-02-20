package com.app;

import io.vertx.core.AbstractVerticle;
import io.vertx.core.Future;
import io.vertx.core.Promise;
import io.vertx.core.Vertx;
import io.vertx.core.MultiMap;
import io.vertx.core.json.JsonArray;
import io.vertx.core.json.JsonObject;
import io.vertx.core.buffer.Buffer;
import io.vertx.ext.web.Router;
import io.vertx.ext.web.RoutingContext;
import io.vertx.ext.web.handler.BodyHandler;
import io.vertx.ext.web.client.HttpRequest;
import io.vertx.ext.web.client.WebClient;
import io.vertx.ext.web.client.WebClientOptions;

import java.lang.reflect.Array;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import java.util.stream.Collectors;

public class VerifyTransaction extends AbstractVerticle {

  // Required environment variables
  private static final String DIRECTUS_URL = System.getenv("DIRECTUS_URL");
  private static final String DIRECTUS_TOKEN = System.getenv("DIRECTUS_TOKEN");
  private static final String K_SINK = System.getenv("K_SINK");
  private static final String OTP_SECRET = System.getenv("OTP_SECRET");
  private static final double MAX_AMOUNT = System.getenv("MAX_AMOUNT") != null
      ? Double.parseDouble(System.getenv("MAX_AMOUNT"))
      : 0;

  // Headers to remove from incoming request when forwarding.
  private static final String[] HEADERS_REMOVE = new String[]{
      "ce-id", "ce-specversion", "ce-type", "ce-source", "content-type", "host", "x-k-sink"
  };

  private WebClient webClient;

  @Override
  public void start(Promise<Void> startPromise) {
    if (DIRECTUS_URL == null || DIRECTUS_TOKEN == null || OTP_SECRET == null || MAX_AMOUNT == 0) {
      startPromise.fail("Missing required environment variables: DIRECTUS_URL, DIRECTUS_TOKEN, MAX_AMOUNT, OTP_SECRET");
      return;
    }
    if (K_SINK == null) {
      System.out.println("Warning: K_SINK is not set. Events will not be forwarded.");
    }

    webClient = WebClient.create(vertx, new WebClientOptions().setSsl(false));

    Router router = Router.router(vertx);
    router.route().handler(BodyHandler.create());
    router.post("/").handler(this::handleTransaction);

    vertx.createHttpServer()
         .requestHandler(router)
         .listen(8080, http -> {
           if (http.succeeded()) {
             startPromise.complete();
             System.out.println("Server started on port 8080");
           } else {
             startPromise.fail(http.cause());
           }
         });
  }

  private void handleTransaction(RoutingContext ctx) {
    JsonObject requestBody = ctx.getBodyAsJson();
    if (requestBody == null) {
      forwardToBroker(ctx, new JsonObject(), false, "Invalid JSON", 400);
      return;
    }
    
    // Use atomic containers to allow modifications within lambdas.
    final AtomicBoolean proceedRef = new AtomicBoolean(true);
    final AtomicReference<String> messageRef = new AtomicReference<>("Forwarded");
    final AtomicInteger statusCodeRef = new AtomicInteger(200);
    double amount = 0;

    // Parse "amount"
    try {
      Object amtObj = requestBody.getValue("amount");
      if (amtObj instanceof Number) {
        amount = ((Number) amtObj).doubleValue();
      } else if (amtObj instanceof String) {
        amount = Double.parseDouble((String) amtObj);
      } else {
        throw new Exception("Invalid type");
      }
    } catch (Exception e) {
      proceedRef.set(false);
      messageRef.set("Invalid amount provided");
      statusCodeRef.set(400);
    }

    String clientUsername = requestBody.getString("client");
    String destinationClient = requestBody.getString("destination_client");
    String otp = requestBody.getString("otp");

    // Check OTP if amount exceeds MAX_AMOUNT.
    if (statusCodeRef.get() == 200 && amount > MAX_AMOUNT && (otp == null || !otp.equals(OTP_SECRET))) {
      proceedRef.set(false);
      messageRef.set("OTP required or incorrect");
      statusCodeRef.set(403);
    }

    String req_id = ctx.request().getHeader("Ce-Id");

    // Synchronously retrieve user IDs for both client and destination_client.
    Future<Integer> fromFuture = getUserId(clientUsername, req_id);
    Future<Integer> toFuture = fromFuture.compose(clientId -> getUserId(destinationClient, req_id));

    io.vertx.core.CompositeFuture.all(fromFuture, toFuture).onComplete(ar -> {
      Integer fromId = fromFuture.result();
      Integer toId = toFuture.result();
      if (statusCodeRef.get() == 200 && (fromId == null || toId == null)) {
        proceedRef.set(false);
        messageRef.set("Invalid client usernames");
        statusCodeRef.set(400);
      }
      // Build payload with additional fields.
      JsonObject payload = requestBody.copy();
      payload.put("message", messageRef.get());
      payload.put("from", fromId);
      payload.put("to", toId);
      forwardToBroker(ctx, payload, proceedRef.get(), messageRef.get(), statusCodeRef.get());
    });
  }

  /**
   * Retrieves a user ID from Directus given a username.
   */
  private Future<Integer> getUserId(String username, String req_id) {
    Promise<Integer> promise = Promise.promise();
    if (username == null) {
      promise.complete(null);
      return promise.future();
    }
    String url = DIRECTUS_URL + "/items/users?filter[username][_eq]=" + username;
    webClient.getAbs(url)
             .putHeader("Authorization", "Bearer " + DIRECTUS_TOKEN)
             .putHeader("Ce-Id", req_id)
             .send(ar -> {
               if (ar.succeeded() && ar.result().statusCode() == 200) {
                 JsonObject body = ar.result().bodyAsJsonObject();
                 if (body != null) {
                   JsonArray data = body.getJsonArray("data");
                   if (data != null && !data.isEmpty()) {
                     Integer id = data.getJsonObject(0).getInteger("id");
                     promise.complete(id);
                     return;
                   }
                 }
               }
               promise.complete(null);
             });
    return promise.future();
  }

  /**
   * Forwards the transaction payload to the external broker (K_SINK) and responds to the original requester.
   * Outgoing headers are constructed to prevent overrides by incoming headers.
   */
  private void forwardToBroker(RoutingContext ctx, JsonObject payload, boolean proceed, String message, int statusCode) {
    MultiMap headers = MultiMap.caseInsensitiveMultiMap();

    // Copy allowed incoming headers
    for (Map.Entry<String, String> entry : ctx.request().headers()) {
        String key = entry.getKey();
        if (!Arrays.asList(HEADERS_REMOVE).contains(key.toLowerCase())) {
            headers.set(key, entry.getValue()); // Override any incorrect headers
        }
    }

    // Set additional headers
    headers.set("Ce-Id", ctx.request().getHeader("Ce-Id"));
    headers.set("Ce-Specversion", "1.0");
    headers.set("Ce-Type", "transaction");
    headers.set("Ce-Source", "verify-transaction");
    headers.set("Ce-Dt", String.valueOf(proceed).toLowerCase());
    headers.set("Content-Type", "application/json"); // Ensure this is set

    // Log headers to confirm they are being set
    headers.forEach(entry -> System.out.println("Setting Header: " + entry.getKey() + " = " + entry.getValue()));

    // Determine target sink
    String targetSink = ctx.request().getHeader("X-K-Sink");
    if (targetSink == null || targetSink.isEmpty()) {
        targetSink = K_SINK;
    }

    if (targetSink != null) {
        HttpRequest<Buffer> request = webClient.postAbs(targetSink);

        // Set headers explicitly
        headers.forEach(entry -> request.putHeader(entry.getKey(), entry.getValue()));

        request.sendJsonObject(payload).onComplete(ar -> {
            if (ar.succeeded()) {
                System.out.println("Successfully forwarded event");
            } else {
                System.out.println("Failed to forward event" + " Error: " + ar.cause().getMessage());
            }

            // Prevent duplicate response
            if (!ctx.response().ended()) {
                JsonObject responsePayload = new JsonObject().put("message", message);
                ctx.response()
                   .setStatusCode(statusCode)
                   .putHeader("Content-Type", "application/json")
                   .end(responsePayload.encode());
            }
        });
      } else {
          System.out.println("Warning: No valid sink configured. Event not forwarded.");
          if (!ctx.response().ended()) {
              JsonObject responsePayload = new JsonObject().put("message", message);
              ctx.response()
                .setStatusCode(statusCode)
                .putHeader("Content-Type", "application/json")
                .end(responsePayload.encode());
          }
      }
  }



  public static void main(String[] args) {
    Vertx vertx = Vertx.vertx();
    vertx.deployVerticle(new VerifyTransaction());
  }
}
