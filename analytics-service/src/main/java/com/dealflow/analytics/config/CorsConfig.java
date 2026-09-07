package com.dealflow.analytics.config;

import java.util.List;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.CorsRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

/**
 * The dashboard calls this service directly rather than proxying through the CRM,
 * so the browser needs explicit permission for that cross-origin request.
 *
 * <p>Origins are listed, never {@code *}: the Authorization header is a credential,
 * and a wildcard origin would be both refused by the browser and wrong in
 * principle.
 */
@Configuration
public class CorsConfig implements WebMvcConfigurer {

    private final List<String> allowedOrigins;

    public CorsConfig(
            @Value("${analytics.cors.origins:http://localhost:3000,http://127.0.0.1:3000}")
                    String origins) {
        this.allowedOrigins = List.of(origins.split(","));
    }

    @Override
    public void addCorsMappings(CorsRegistry registry) {
        registry.addMapping("/**")
                .allowedOrigins(allowedOrigins.toArray(String[]::new))
                .allowedMethods("GET", "POST", "PATCH", "OPTIONS")
                .allowedHeaders("*")
                .allowCredentials(true);
    }
}
