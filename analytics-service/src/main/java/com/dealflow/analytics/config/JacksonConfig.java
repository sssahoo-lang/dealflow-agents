package com.dealflow.analytics.config;

import com.fasterxml.jackson.core.JsonGenerator;
import com.fasterxml.jackson.databind.JsonSerializer;
import com.fasterxml.jackson.databind.SerializerProvider;
import com.fasterxml.jackson.databind.module.SimpleModule;
import java.io.IOException;
import java.math.BigDecimal;
import java.math.RoundingMode;
import org.springframework.boot.autoconfigure.jackson.Jackson2ObjectMapperBuilderCustomizer;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Money leaves this service as a string, exactly as it arrived from the CRM.
 *
 * <p>A JSON number would be read as a double by most clients, and 142500.75 does
 * not survive that round trip intact. The producer already made this choice on
 * the way in; breaking it on the way out would defeat the point of carrying
 * BigDecimal through the middle.
 *
 * <p>Only BigDecimal is affected. Rates and probabilities are doubles by design
 * and stay numbers, since approximating 0.583 is harmless.
 */
@Configuration
public class JacksonConfig {

    /** Two decimal places, always: "1000.00" rather than "1000.0" or "1E+3". */
    private static class MoneyAsStringSerializer extends JsonSerializer<BigDecimal> {
        @Override
        public void serialize(BigDecimal value, JsonGenerator gen, SerializerProvider provider)
                throws IOException {
            gen.writeString(value.setScale(2, RoundingMode.HALF_UP).toPlainString());
        }
    }

    @Bean
    public Jackson2ObjectMapperBuilderCustomizer moneyAsString() {
        return builder -> {
            SimpleModule module = new SimpleModule();
            module.addSerializer(BigDecimal.class, new MoneyAsStringSerializer());
            // modulesToInstall, NOT modules: modules() REPLACES the module list and
            // would silently drop Spring Boot's auto-registered JavaTimeModule,
            // breaking every Instant in a response.
            builder.modulesToInstall(module);
        };
    }
}
