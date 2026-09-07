package com.dealflow.analytics.contract;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

import com.dealflow.analytics.outbox.handler.DealEventHandler;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.HashSet;
import java.util.Set;
import java.util.stream.StreamSupport;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * The cross-language contract, asserted from the consumer's side.
 *
 * <p>These read {@code contracts/events/deal.created.v1.json} -- the very same
 * file {@code tests/test_outbox.py} asserts on the producer's side. Not a copy:
 * one file, two languages. If Python changes the payload shape without updating
 * the contract, its own test fails; if it updates the contract without this
 * service adapting, these fail. Neither side can move alone.
 *
 * <p>Pure unit tests: no Spring, no database. The contract is a document, and
 * checking a document against a class needs neither.
 */
@DisplayName("Event contract")
class EventContractTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    /** Mounted at /build/contracts in the test container; ../contracts locally. */
    private static Path contractFile() {
        Path inContainer = Path.of("/build/contracts/events/deal.created.v1.json");
        return Files.exists(inContainer)
                ? inContainer
                : Path.of("..", "contracts", "events", "deal.created.v1.json");
    }

    private static JsonNode contract() throws Exception {
        Path path = contractFile();
        assumeTrue(Files.exists(path), "contract fixture not mounted at " + path);
        return MAPPER.readTree(Files.readString(path));
    }

    private static Set<String> declaredKeys(JsonNode contract) {
        Set<String> keys = new HashSet<>();
        contract.get("payload_keys").forEach(node -> keys.add(node.asText()));
        return keys;
    }

    @Test
    @DisplayName("this service reads no field the contract does not promise")
    void readsOnlyPromisedFields() throws Exception {
        Set<String> promised = declaredKeys(contract());

        assertThat(DealEventHandler.CREATED_PAYLOAD_FIELDS)
                .as("a field read here but absent from the contract breaks the day "
                        + "the producer stops sending it")
                .isSubsetOf(promised);
    }

    @Test
    @DisplayName("the contract still names the event type this service handles")
    void eventTypeStillHandled() throws Exception {
        String eventType = contract().get("event_type").asText();

        assertThat(new DealEventHandler(null).handles())
                .as("the producer renamed the event and this consumer would go deaf")
                .contains(eventType);
    }

    @Test
    @DisplayName("the contract version matches the one this service expects")
    void versionMatches() throws Exception {
        assertThat(contract().get("event_version").asInt())
                .as("a version bump means the payload shape changed; adapt deliberately")
                .isEqualTo(1);
    }

    @Test
    @DisplayName("the denormalised fields the read model depends on are still promised")
    void denormalisedFieldsSurvive() throws Exception {
        Set<String> promised = declaredKeys(contract());

        // These exist purely so this service never needs access to the CRM's
        // users or companies tables. Losing them would force a schema-level
        // coupling the whole design is built to avoid.
        assertThat(promised).contains("owner_email", "owner_name", "company_name");
    }

    @Test
    @DisplayName("money is documented as a string and parses exactly")
    void moneyIsAStringAndExact() throws Exception {
        assertThat(contract().get("notes").get("value").asText())
                .contains("string")
                .contains("never a JSON number");

        // The reason the contract says so: via double, this value does not survive.
        JsonNode payload = MAPPER.readTree("{\"value\": \"142500.75\"}");
        assertThat(new BigDecimal(payload.get("value").asText()))
                .isEqualByComparingTo("142500.75");
    }

    @Test
    @DisplayName("a JSON number would silently lose precision, which is why it is banned")
    void demonstratesWhyMoneyIsNotANumber() throws Exception {
        // Not a test of our code -- a test of the reasoning behind the rule, so
        // nobody 'simplifies' the contract later without meeting this.
        JsonNode asNumber = MAPPER.readTree("{\"value\": 0.1}");
        double a = asNumber.get("value").asDouble();

        assertThat(BigDecimal.valueOf(a + 0.2))
                .as("floating point addition does not give exactly 0.3")
                .isNotEqualByComparingTo("0.3");
        assertThat(new BigDecimal("0.1").add(new BigDecimal("0.2")))
                .as("string-sourced BigDecimal does")
                .isEqualByComparingTo("0.3");
    }

    @Test
    @DisplayName("timestamps carry an explicit UTC offset and parse to an Instant")
    void timestampsAreUnambiguous() throws Exception {
        assertThat(contract().get("notes").get("created_at").asText())
                .contains("ISO 8601");

        // The producer emits "+00:00"; a naive string would be a guess at the zone.
        String fromProducer = "2026-09-04T10:15:30+00:00";
        assertThat(Instant.parse(fromProducer.replace("+00:00", "Z")))
                .isEqualTo(Instant.parse("2026-09-04T10:15:30Z"));
    }

    @Test
    @DisplayName("every promised key is a plain snake_case name")
    void keysAreWellFormed() throws Exception {
        JsonNode keys = contract().get("payload_keys");

        assertThat(StreamSupport.stream(keys.spliterator(), false).map(JsonNode::asText))
                .allSatisfy(key -> assertThat(key).matches("[a-z][a-z0-9_]*"));
    }
}
