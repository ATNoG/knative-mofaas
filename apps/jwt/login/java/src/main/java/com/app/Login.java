package com.app;

import io.vertx.core.AbstractVerticle;
import io.vertx.core.Future;
import io.vertx.core.Promise;
import io.vertx.core.Vertx;
import io.vertx.core.json.JsonObject;
import io.vertx.ext.auth.jwt.JWTAuth;
import io.vertx.ext.auth.jwt.JWTAuthOptions;
import io.vertx.ext.web.Router;
import io.vertx.ext.web.RoutingContext;
import io.vertx.ext.web.handler.BodyHandler;
import io.vertx.ext.web.client.WebClient;
import io.vertx.ext.web.client.HttpResponse;
import io.vertx.ext.web.client.WebClientOptions;

import io.vertx.ext.auth.JWTOptions;
import io.vertx.ext.auth.PubSecKeyOptions;

import java.util.concurrent.atomic.AtomicReference;

import at.favre.lib.crypto.bcrypt.BCrypt;

public class Login extends AbstractVerticle {
    private static final String DIRECTUS_URL = System.getenv("DIRECTUS_URL");
    private static final String SECRET_KEY = System.getenv("SECRET_KEY");
    private static final String DIRECTUS_TOKEN = System.getenv("DIRECTUS_TOKEN");
    private static final int EXPIRATION = 3600;

    private WebClient webClient;
    private JWTAuth jwtAuth;

    @Override
    public void start(Promise<Void> startPromise) {
        if (DIRECTUS_URL == null || SECRET_KEY == null || DIRECTUS_TOKEN == null) {
            startPromise.fail("Missing required environment variables: DIRECTUS_URL, SECRET_KEY, DIRECTUS_TOKEN");
            return;
        }

        webClient = WebClient.create(vertx, new WebClientOptions().setSsl(false));
        jwtAuth = JWTAuth.create(vertx, new JWTAuthOptions()
            .addPubSecKey(new PubSecKeyOptions()
                .setAlgorithm("HS256")
                .setBuffer(SECRET_KEY)));

        Router router = Router.router(vertx);
        router.route().handler(BodyHandler.create());
        router.post("/").handler(this::handleLogin);

        vertx.createHttpServer().requestHandler(router).listen(8080, result -> {
            if (result.succeeded()) {
                startPromise.complete();
            } else {
                startPromise.fail(result.cause());
            }
        });
    }

    private void handleLogin(RoutingContext context) {
        JsonObject body = context.body().asJsonObject();
        if (body == null || !body.containsKey("username") || !body.containsKey("password")) {
            context.response().setStatusCode(400).end(new JsonObject().put("error", "Missing credentials").encode());
            return;
        }

        String username = body.getString("username");
        String password = body.getString("password");

        verifyCredentials(username, password).compose(isValid -> {
            if (isValid) {
                return checkAccess(username) // First, check access
                    .compose(hasAccess -> generateJwt(username, hasAccess)); // Then, generate JWT
            } else {
                return Future.failedFuture("Invalid username or password");
            }
        }).onSuccess(jwt -> {
            context.response().setStatusCode(200).putHeader("Authorization", "Bearer " + jwt).end();
        }).onFailure(err -> {
            if ("Invalid username or password".equals(err.getMessage())) {
                context.response().setStatusCode(401).end(new JsonObject().put("error", err.getMessage()).encode());
            } else {
                context.response().setStatusCode(500).end(new JsonObject().put("error", "Internal server error").encode());
            }
        });
    }

    private Future<Boolean> verifyCredentials(String username, String password) {
        Promise<Boolean> promise = Promise.promise();
        String url = DIRECTUS_URL + "/items/users?filter[username][_eq]=" + username;

        webClient.getAbs(url)
            .putHeader("Authorization", "Bearer " + DIRECTUS_TOKEN)
            .send(ar -> {
                if (ar.succeeded()) {
                    HttpResponse<?> response = ar.result();
                    JsonObject jsonResponse = response.bodyAsJsonObject();
                    if (jsonResponse != null && jsonResponse.containsKey("data") && jsonResponse.getJsonArray("data").size() > 0) {
                        String storedHash = jsonResponse.getJsonArray("data").getJsonObject(0).getString("password");
                        boolean isValid = BCrypt.verifyer().verify(password.toCharArray(), storedHash).verified;
                        promise.complete(isValid);
                    } else {
                        promise.complete(false);
                    }
                } else {
                    promise.fail(ar.cause());
                }
            });
        return promise.future();
    }

    private Future<Boolean> checkAccess(String username) {
        Promise<Boolean> promise = Promise.promise();
        String url = DIRECTUS_URL + "/items/users?filter[username][_eq]=" + username;
    
        webClient.getAbs(url)
            .putHeader("Authorization", "Bearer " + DIRECTUS_TOKEN)
            .send(ar -> {
                if (ar.succeeded()) {
                    HttpResponse<?> response = ar.result();
                    JsonObject jsonResponse = response.bodyAsJsonObject();
                    boolean hasAccess = jsonResponse != null 
                                        && jsonResponse.containsKey("data") 
                                        && jsonResponse.getJsonArray("data").size() > 0 
                                        && jsonResponse.getJsonArray("data").getJsonObject(0).getBoolean("has_access", false);
                    promise.complete(hasAccess);
                } else {
                    promise.fail(ar.cause());
                }
            });
    
        return promise.future();
    }

    private Future<String> generateJwt(String username, boolean hasAccess) {
        Promise<String> promise = Promise.promise();

        // Generate JWT immediately after successful login
        JsonObject payload = new JsonObject()
            .put("sub", username)
            .put("iat", System.currentTimeMillis() / 1000)
            .put("exp", (System.currentTimeMillis() / 1000) + EXPIRATION)
            .put("has_access", hasAccess);

        String token = jwtAuth.generateToken(payload, new JWTOptions().setAlgorithm("HS256"));
        promise.complete(token);

        return promise.future();
    }

    public static void main(String[] args) {
        Vertx vertx = Vertx.vertx();
        vertx.deployVerticle(new Login());
    }
}
