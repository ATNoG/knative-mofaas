package com.app;

import io.vertx.core.AbstractVerticle;
import io.vertx.core.Promise;
import io.vertx.core.Vertx;
import io.vertx.core.http.HttpMethod;
import io.vertx.core.json.JsonArray;
import io.vertx.core.json.JsonObject;
import io.vertx.ext.auth.jwt.JWTAuth;
import io.vertx.ext.auth.jwt.JWTAuthOptions;
import io.vertx.ext.auth.PubSecKeyOptions;
import io.vertx.ext.web.Router;
import io.vertx.ext.web.RoutingContext;
import io.vertx.ext.web.handler.BodyHandler;
import io.vertx.ext.web.client.WebClient;
import io.vertx.ext.web.client.WebClientOptions;
import io.vertx.ext.auth.authentication.TokenCredentials;

import java.time.Instant;
import java.time.ZoneOffset;
import java.time.ZonedDateTime;

public class GetSecret extends AbstractVerticle {

  private static final String DIRECTUS_URL = System.getenv("DIRECTUS_URL");
  private static final String SECRET_KEY = System.getenv("SECRET_KEY");
  private static final String DIRECTUS_TOKEN = System.getenv("DIRECTUS_TOKEN");
  // private static final int EXPIRATION = 3600; // 1 hour

  private JWTAuth jwtAuth;
  private WebClient webClient;

  private void getSecret(RoutingContext context) {
    String authHeader = context.request().getHeader("Authorization");
    if (authHeader == null || !authHeader.startsWith("Bearer ")) {
      context.response().setStatusCode(401).end("{\"error\": \"Missing or invalid token\"}");
      return;
    }
    String token = authHeader.substring(7); // Remove "Bearer "

    // Authenticate asynchronously using Vert.x JWT
    jwtAuth.authenticate(new TokenCredentials(token))
      .onSuccess(user -> {
        // Check the 'iat' (issued at) claim
        // Long issuedAt = user.principal().getLong("iat", 0L);
        // if (issuedAt == 0) {
        //   context.response().setStatusCode(401).end("{\"error\": \"Invalid token: missing iat\"}");
        //   return;
        // }
        // ZonedDateTime issuedAtDateTime = ZonedDateTime.ofInstant(Instant.ofEpochSecond(issuedAt), ZoneOffset.UTC);
        // ZonedDateTime now = ZonedDateTime.now(ZoneOffset.UTC);
        // if (now.isAfter(issuedAtDateTime.plusSeconds(EXPIRATION))) {
        //   context.response().setStatusCode(401).end("{\"error\": \"Token expired\"}");
        //   return;
        // }
        // Check the 'has_access' claim
        if (!user.principal().getBoolean("has_access", false)) {
          context.response().setStatusCode(403).end("{\"error\": \"Access denied\"}");
          return;
        }
        // If valid, retrieve the secret from Directus
        getSecretFromDatabase(context);
      })
      .onFailure(err -> {
        context.response().setStatusCode(401).end("{\"error\": \"Invalid token\"}");
      });
  }

  private void getSecretFromDatabase(RoutingContext context) {
    String url = DIRECTUS_URL + "/items/secrets";
    // Use WebClient's getAbs to make an HTTP GET request
    webClient.getAbs(url)
      .putHeader("Authorization", "Bearer " + DIRECTUS_TOKEN)
      .send()
      .onSuccess(response -> {
        JsonObject responseJson = response.bodyAsJsonObject();
        if (responseJson == null || !responseJson.containsKey("data")) {
          context.response().setStatusCode(404).end("{\"error\": \"No secret found\"}");
          return;
        }
        JsonArray dataArray = responseJson.getJsonArray("data");
        if (dataArray.isEmpty()) {
          context.response().setStatusCode(404).end("{\"error\": \"No secret found\"}");
          return;
        }
        JsonObject data = dataArray.getJsonObject(0);
        if (data != null && data.containsKey("value")) {
          context.response().end(data.getString("value"));
        } else {
          context.response().setStatusCode(404).end("{\"error\": \"No secret found\"}");
        }
      })
      .onFailure(err -> {
        context.response().setStatusCode(500).end("{\"error\": \"Internal server error\"}");
      });
  }

  @Override
  public void start(Promise<Void> startPromise) {
    if (DIRECTUS_URL == null || SECRET_KEY == null || DIRECTUS_TOKEN == null) {
      startPromise.fail("Missing required environment variables: DIRECTUS_URL, SECRET_KEY, DIRECTUS_TOKEN");
      return;
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
    router.get("/").handler(this::getSecret);

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
    vertx.deployVerticle(new GetSecret());
  }
} 