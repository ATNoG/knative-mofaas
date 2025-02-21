package com.app;

import io.vertx.core.AbstractVerticle;
import io.vertx.core.Promise;
import io.vertx.core.Vertx;
import io.vertx.core.MultiMap;
import io.vertx.core.json.JsonObject;
import io.vertx.core.buffer.Buffer;
import io.vertx.ext.auth.authentication.TokenCredentials;
import io.vertx.ext.auth.jwt.JWTAuth;
import io.vertx.ext.auth.jwt.JWTAuthOptions;
import io.vertx.ext.auth.PubSecKeyOptions;
import io.vertx.ext.web.Router;
import io.vertx.ext.web.RoutingContext;
import io.vertx.ext.web.handler.BodyHandler;
import io.vertx.ext.web.client.HttpRequest;
import io.vertx.ext.web.client.WebClient;
import io.vertx.ext.web.client.WebClientOptions;

import java.util.Arrays;
import java.util.Map;

public class Authorization extends AbstractVerticle {

  private static final String SECRET_KEY = System.getenv("SECRET_KEY");
  private static final String K_SINK = System.getenv("K_SINK");
  // private static final int EXPIRATION = 3600; // 1 hour

  // List of headers to remove when copying over others.
  private static final String[] HEADERS_REMOVE = new String[]{"Ce-Id", "Ce-Specversion", "Ce-Type", "Ce-Source", "Content-Type", "Host", "X-K-Sink"};

  private JWTAuth jwtAuth;
  private WebClient webClient;

  private void verifyToken(RoutingContext context) {
    String authHeader = context.request().getHeader("Authorization");
    if (authHeader == null || !authHeader.startsWith("Bearer ")) {
      forwardToBroker(context, null, "Missing or invalid token", 401);
      return;
    }
    String token = authHeader.substring(7);

    jwtAuth.authenticate(new TokenCredentials(token))
      .onSuccess(user -> {
        JsonObject principal = user.principal();
        boolean hasAccess = principal.getBoolean("has_access", false);
        String client = principal.getString("sub", "unknown");
        
        if (!hasAccess) {
          forwardToBroker(context, client, "Access denied", 403);
        } else {
          forwardToBroker(context, client, "Forwarded", 200);
        }
      })
      .onFailure(err -> {
        forwardToBroker(context, null, "Invalid token", 401);
      });
  }

  private void forwardToBroker(RoutingContext context, String client, String message, int statusCode) {
    // Merge the original request JSON (if any) with additional fields.
    JsonObject originalBody = context.getBodyAsJson();
    JsonObject payload = new JsonObject();
    if (originalBody != null) {
      payload.mergeIn(originalBody);
    }
    payload.put("client", client);
    payload.put("message", message);

    // Build headers for the outgoing POST.
    boolean proceed = (statusCode == 200);
    MultiMap headers = MultiMap.caseInsensitiveMultiMap();
    String ceId = context.request().getHeader("Ce-Id");
    if (ceId != null) {
      headers.add("Ce-Id", ceId);
    }
    headers.add("Ce-Specversion", "1.0");
    headers.add("Ce-Type", "authorization");
    headers.add("Ce-Source", "authorization");
    headers.add("Content-Type", "application/json");
    headers.add("Ce-dv", String.valueOf(proceed));

    // Copy additional headers, excluding specific ones.
    for (Map.Entry<String, String> entry : context.request().headers()) {
      String key = entry.getKey();
      if (!Arrays.asList(HEADERS_REMOVE).contains(key)) {
        headers.add(key, entry.getValue());
      }
    }

    // Forward the payload to K_SINK using a POST request, if configured.
    String kSinkHeader = context.request().getHeader("X-K-SINK");
    String targetSink = (kSinkHeader != null && !kSinkHeader.isEmpty()) ? kSinkHeader : K_SINK;

    if (targetSink != null) {
        HttpRequest<Buffer> request = webClient.postAbs(targetSink);
        request.headers().addAll(headers);
        request.sendJsonObject(payload).onComplete(ar -> {
            if (ar.succeeded()) {
                System.out.println("Successfully forwarded event to: " + targetSink + " Response: " + ar.result().bodyAsString());
            } else {
                System.out.println("Failed to forward event to: " + targetSink + " Error: " + ar.cause().getMessage());
            }
            // Prevent duplicate response
            if (!context.response().ended()) {
              // Respond to the original requester.
              JsonObject responsePayload = new JsonObject().put("message", message);
              context.response().setStatusCode(statusCode).putHeader("Content-Type", "application/json").end(responsePayload.encode());
          }
        });
    } else {
        System.out.println("Warning: No valid sink configured. Event not forwarded.");
        // Respond to the original requester.
        JsonObject responsePayload = new JsonObject().put("message", message);
        context.response().setStatusCode(statusCode).putHeader("Content-Type", "application/json").end(responsePayload.encode());
    }
  }

  @Override
  public void start(Promise<Void> startPromise) {
    if (SECRET_KEY == null) {
      startPromise.fail("Missing required environment variable: SECRET_KEY");
      return;
    }

    if (K_SINK == null) {
      System.out.println("Warning: K_SINK is not set. Events will not be forwarded.");
    }

    // Configure JWTAuth using HS256 with the provided secret.
    jwtAuth = JWTAuth.create(vertx, new JWTAuthOptions()
            .addPubSecKey(new PubSecKeyOptions()
                .setAlgorithm("HS256")
                .setBuffer(SECRET_KEY)));

    // Create WebClient for making HTTP requests
    webClient = WebClient.create(vertx, new WebClientOptions().setSsl(false));

    Router router = Router.router(vertx);
    router.route().handler(BodyHandler.create());
    router.post("/").handler(this::verifyToken);

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

  public static void main(String[] args) {
    Vertx vertx = Vertx.vertx();
    vertx.deployVerticle(new Authorization());
  }
} 