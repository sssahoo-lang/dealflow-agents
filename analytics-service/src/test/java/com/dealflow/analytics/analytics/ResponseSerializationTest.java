package com.dealflow.analytics.analytics;

import static org.assertj.core.api.Assertions.assertThat;

import com.dealflow.analytics.dto.ForecastResponse;
import com.dealflow.analytics.dto.LeaderboardRow;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;

/**
 * Serialisation is part of the API contract, so it gets its own tests.
 *
 * <p>These exist because the repository tests never touched Jackson: a config
 * change that replaced the module list instead of adding to it silently broke
 * every Instant in a response, and only a live request revealed it.
 */
@SpringBootTest
@ActiveProfiles("test")
@DisplayName("Response serialisation")
class ResponseSerializationTest {

    @Autowired private ObjectMapper objectMapper;

    @Test
    @DisplayName("money is a string with two decimals, never a JSON number")
    void moneyIsAString() throws Exception {
        LeaderboardRow row = new LeaderboardRow(
                1L, "Rep", "rep@x.test", 2, 1,
                new BigDecimal("142500.75"), new BigDecimal("1000"), 0.667, 12.5);

        String json = objectMapper.writeValueAsString(row);

        assertThat(json).contains("\"wonValue\":\"142500.75\"");
        // Trailing zeros preserved: a client parsing "1000.00" gets exact cents.
        assertThat(json).contains("\"openValue\":\"1000.00\"");
    }

    @Test
    @DisplayName("rates stay numbers")
    void ratesAreNotStrings() throws Exception {
        LeaderboardRow row = new LeaderboardRow(
                1L, "Rep", "rep@x.test", 2, 1,
                BigDecimal.ONE, BigDecimal.ONE, 0.5, 12.5);

        assertThat(objectMapper.writeValueAsString(row)).contains("\"winRate\":0.5");
    }

    @Test
    @DisplayName("Instant serialises without the JavaTimeModule being clobbered")
    void instantsSerialise() throws Exception {
        // Regression: the money serializer was registered with modules(), which
        // REPLACES the module list and dropped jackson-datatype-jsr310, so every
        // endpoint returning a timestamp 500'd.
        String json = objectMapper.writeValueAsString(Map.of("at", Instant.parse("2026-09-04T10:15:30Z")));

        assertThat(json).contains("2026-09-04");
    }

    @Test
    @DisplayName("a forecast round-trips with money as strings and a real timestamp")
    void forecastSerialises() throws Exception {
        ForecastResponse forecast = new ForecastResponse(
                3, Instant.parse("2026-09-04T10:15:30Z"),
                new BigDecimal("37500.25"), new BigDecimal("75000.50"),
                1, new BigDecimal("12345.00"),
                List.of(new ForecastResponse.ForecastBucket(
                        "2026-10", new BigDecimal("37500.25"), new BigDecimal("75000.50"), 1)));

        String json = objectMapper.writeValueAsString(forecast);

        assertThat(json).contains("\"weightedTotal\":\"37500.25\"");
        assertThat(json).contains("\"unscheduledValue\":\"12345.00\"");
        assertThat(json).contains("2026-09-04");
    }

    @Test
    @DisplayName("nulls stay null rather than becoming zero")
    void nullsSurvive() throws Exception {
        LeaderboardRow noClosedDeals = new LeaderboardRow(
                1L, "Rep", "rep@x.test", 0, 0, BigDecimal.ZERO, BigDecimal.ZERO, null, null);

        String json = objectMapper.writeValueAsString(noClosedDeals);

        assertThat(json).contains("\"winRate\":null");
        assertThat(json).contains("\"avgDaysToClose\":null");
    }
}
