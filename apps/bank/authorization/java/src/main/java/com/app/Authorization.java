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

import java.util.Arrays;
import java.util.Map;

public class VerifyTransaction extends AbstractVerticle {

  // Environment variables (must be set)
  private static final String DIRECTUS_URL = System.getenv("DIRECTUS_URL");
  private static final String DIRECTUS_TOKEN = System.getenv("DIRECTUS_TOKEN");
  private static final String K_SINK = System.getenv("K_SINK");
  private static final String OTP_SECRET = System.getenv("OTP_SECRET");
  private static final double MAX_AMOUNT = System.getenv("MAX_AMOUNT") != null
      ? Double.parseDouble(System.getenv("MAX_AMOUNT"))
      : 0;

  // Headers that should not be carried over from the incoming request.
  private static final String[] HEADERS_REMOVE = new String[]{
      "Ce-Id", "Ce-Specversion", "Ce-Type", "Ce-Source", "Content-Type", "Host", "X-K-Sink"
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

    // Create WebClient (disable SSL if not needed)
    webClient = WebClient.create(vertx, new WebClientOptions().setSsl(false));

    Router router = Router.router(vertx);
    // Enable body handling (so request.getBodyAsJson() works)
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

  /**
   * Handles the transaction request:
   * - Parses JSON body and validates the amount.
   * - Checks OTP if amount exceeds MAX_AMOUNT.
   * - Retrieves user IDs for the client and destination_client.
   * - Merges additional fields into the payload.
   * - Forwards the payload to the broker and responds to the caller.
   */
  private void handleTransaction(RoutingContext ctx) {
    JsonObject requestBody = ctx.getBodyAsJson();
    if (requestBody == null) {
      forwardToBroker(ctx, new JsonObject(), false, "Invalid JSON", 400);
      return;
    }
    boolean proceed = true;
    String message = "Forwarded";
    int statusCode = 200;
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
      proceed = false;
      message = "Invalid amount provided";
      statusCode = 400;
    }

    String clientUsername = requestBody.getString("client");
    String destinationClient = requestBody.getString("destination_client");
    String otp = requestBody.getString("otp");

    // If amount exceeds limit, ensure OTP matches
    if (statusCode == 200 && amount > MAX_AMOUNT && (otp == null || !otp.equals(OTP_SECRET))) {
      proceed = false;
      message = "OTP required or incorrect";
      statusCode = 403;
    }

    // Asynchronously retrieve the user IDs.
    Future<String> fromFuture = getUserId(clientUsername);
    Future<String> toFuture = getUserId(destinationClient);

    io.vertx.core.CompositeFuture.all(fromFuture, toFuture).onComplete(ar -> {
      String fromId = fromFuture.result();
      String toId = toFuture.result();
      if (statusCode == 200 && (fromId == null || toId == null)) {
        proceed = false;
        message = "Invalid client usernames";
        statusCode = 400;
      }
      // Build the payload with additional fields ("message", "from", and "to")
      JsonObject payload = requestBody.copy();
      payload.put("message", message);
      payload.put("from", fromId);
      payload.put("to", toId);
      // Forward the event and respond to the original requester.
      forwardToBroker(ctx, payload, proceed, message, statusCode);
    });
  }

  /**
   * Retrieves a user ID from Directus for a given username.
   */
  private Future<String> getUserId(String username) {
    Promise<String> promise = Promise.promise();
    if (username == null) {
      promise.complete(null);
      return promise.future();
    }
    String url = DIRECTUS_URL + "/items/users?filter[username][_eq]=" + username;
    webClient.getAbs(url)
             .putHeader("Authorization", "Bearer " + DIRECTUS_TOKEN)
             .send(ar -> {
               if (ar.succeeded() && ar.result().statusCode() == 200) {
                 JsonObject body = ar.result().bodyAsJsonObject();
                 if (body != null) {
                   JsonArray data = body.getJsonArray("data");
                   if (data != null && !data.isEmpty()) {
                     String id = data.getJsonObject(0).getString("id");
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
   * Forwards the transaction payload to the external broker (K_SINK) using a POST request,
   * while also responding to the original requester.
   *
   * The outgoing headers are built using fixed values (preventing overrides by the incoming request)
   * and then additional headers are copied (excluding those in HEADERS_REMOVE).
   */
  private void forwardToBroker(RoutingContext ctx, JsonObject payload, boolean proceed, String message, int statusCode) {
    // Build headers for the outgoing request.
    MultiMap headers = MultiMap.caseInsensitiveMultiMap();
    String ceId = ctx.request().getHeader("Ce-Id");
    if (ceId != null) {
      headers.add("Ce-Id", ceId);
    }
    headers.add("Ce-Specversion", "1.0");
    headers.add("Ce-Type", "transaction");
    headers.add("Ce-Source", "verify-transaction");
    headers.add("Content-Type", "application/json");
    headers.add("Ce-Dt", String.valueOf(proceed).toLowerCase());

    // Copy additional headers from the incoming request (skipping ones we must remove)
    for (Map.Entry<String, String> entry : ctx.request().headers()) {
      String key = entry.getKey();
      if (!Arrays.asList(HEADERS_REMOVE).contains(key)) {
        headers.add(key, entry.getValue());
      }
    }

    // Determine the target sink (if "X-K-Sink" header exists, use it; otherwise use K_SINK)
    String kSinkHeader = ctx.request().getHeader("X-K-Sink");
    String targetSink = (kSinkHeader != null && !kSinkHeader.isEmpty()) ? kSinkHeader : K_SINK;

    if (targetSink != null) {
      HttpRequest<Buffer> request = webClient.postAbs(targetSink);
      request.headers().addAll(headers);
      request.sendJsonObject(payload, ar -> {
        if (ar.succeeded()) {
          System.out.println("Successfully forwarded event to: " + targetSink + " Response: " + ar.result().bodyAsString());
        } else {
          System.out.println("Failed to forward event to: " + targetSink + " Error: " + ar.cause().getMessage());
        }
      });
    } else {
      System.out.println("Warning: No valid sink configured. Event not forwarded.");
    }

    // Respond to the original requester.
    JsonObject responsePayload = new JsonObject().put("message", message);
    ctx.response()
       .setStatusCode(statusCode)
       .putHeader("Content-Type", "application/json")
       .end(responsePayload.encode());
  }

  public static void main(String[] args) {
    Vertx vertx = Vertx.vertx();
    vertx.deployVerticle(new VerifyTransaction());
  }
}
