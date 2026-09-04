package com.dealflow.analytics.rules;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.math.BigDecimal;
import java.time.Clock;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneOffset;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

/**
 * The evaluator is a pure function, so these need no Spring context and no
 * database -- they run in milliseconds on every change.
 *
 * <p>The clock is fixed, which is the entire reason it is injected: the 14-day
 * boundary can be asserted exactly rather than approximately.
 */
@DisplayName("Rule evaluator")
class RuleEvaluatorTest {

    private static final Instant NOW = Instant.parse("2026-09-04T12:00:00Z");
    private static final Clock FIXED = Clock.fixed(NOW, ZoneOffset.UTC);

    private final RuleEvaluator evaluator = new RuleEvaluator();
    private final ObjectMapper mapper = new ObjectMapper();

    private Condition condition(String json) throws Exception {
        return ConditionParser.parse(mapper.readTree(json));
    }

    private DealFacts deal(String stage, String value, Instant lastActivity, LocalDate closeDate) {
        return DealFacts.of(
                1L, 2L, stage, new BigDecimal(value), 55.0, "high",
                lastActivity, NOW.minusSeconds(86_400 * 60), closeDate, FIXED);
    }

    private DealFacts staleFor(int days) {
        return deal("negotiation", "50000", NOW.minusSeconds(86_400L * days), null);
    }

    @Nested
    @DisplayName("the 14-day staleness boundary")
    class StalenessBoundary {

        private final String stale14 = """
            {"all":[{"field":"stage","op":"eq","value":"negotiation"},
                    {"field":"days_since_last_activity","op":"gte","value":14}]}""";

        @Test
        @DisplayName("fires at exactly 14 days")
        void firesAtExactly14Days() throws Exception {
            assertThat(evaluator.evaluate(condition(stale14), staleFor(14))).isTrue();
        }

        @Test
        @DisplayName("does not fire at 13 days and 23 hours")
        void doesNotFireJustUnder() throws Exception {
            DealFacts justUnder = deal(
                    "negotiation", "50000",
                    NOW.minusSeconds(86_400L * 14 - 3600), null);

            assertThat(evaluator.evaluate(condition(stale14), justUnder)).isFalse();
        }

        @Test
        @DisplayName("fires well past the threshold")
        void firesWellPast() throws Exception {
            assertThat(evaluator.evaluate(condition(stale14), staleFor(40))).isTrue();
        }

        @Test
        @DisplayName("a deal in another stage never matches, however stale")
        void stageStillGates() throws Exception {
            DealFacts oldButProposal = deal("proposal", "50000", NOW.minusSeconds(86_400L * 90), null);

            assertThat(evaluator.evaluate(condition(stale14), oldButProposal)).isFalse();
        }
    }

    @Nested
    @DisplayName("null semantics")
    class NullSemantics {

        /** Every operator against a null fact is false, except is_null. */
        @Test
        @DisplayName("ordering comparisons are false against a null fact")
        void orderingIsFalseOnNull() throws Exception {
            DealFacts noCloseDate = deal("proposal", "1000", NOW, null);

            for (String op : new String[] {"gt", "gte", "lt", "lte"}) {
                Condition c = condition(
                        "{\"field\":\"expected_close_date_days_remaining\",\"op\":\"" + op
                                + "\",\"value\":0}");
                assertThat(evaluator.evaluate(c, noCloseDate))
                        .as("operator %s against a null fact", op)
                        .isFalse();
            }
        }

        @Test
        @DisplayName("equality is false against a null fact")
        void equalityIsFalseOnNull() throws Exception {
            DealFacts noCloseDate = deal("proposal", "1000", NOW, null);

            assertThat(evaluator.evaluate(
                    condition("{\"field\":\"expected_close_date_days_remaining\",\"op\":\"eq\",\"value\":0}"),
                    noCloseDate)).isFalse();
        }

        @Test
        @DisplayName("neq is ALSO false against a null fact, not true")
        void notEqualsIsAlsoFalseOnNull() throws Exception {
            // The subtle one. "not equal to 5" reads as true for a missing value,
            // but treating absence as a match makes staleness rules fire on every
            // deal that lacks the field.
            DealFacts noCloseDate = deal("proposal", "1000", NOW, null);

            assertThat(evaluator.evaluate(
                    condition("{\"field\":\"expected_close_date_days_remaining\",\"op\":\"neq\",\"value\":5}"),
                    noCloseDate)).isFalse();
        }

        @Test
        @DisplayName("is_null is the one operator that sees null")
        void isNullSeesNull() throws Exception {
            DealFacts noCloseDate = deal("proposal", "1000", NOW, null);
            DealFacts withCloseDate = deal("proposal", "1000", NOW, LocalDate.of(2026, 12, 1));

            Condition c = condition(
                    "{\"field\":\"expected_close_date_days_remaining\",\"op\":\"is_null\"}");
            assertThat(evaluator.evaluate(c, noCloseDate)).isTrue();
            assertThat(evaluator.evaluate(c, withCloseDate)).isFalse();
        }
    }

    @Nested
    @DisplayName("boolean composition")
    class BooleanComposition {

        @Test
        @DisplayName("empty all is true, empty any is false")
        void emptyCollections() throws Exception {
            DealFacts anyDeal = staleFor(1);

            assertThat(evaluator.evaluate(condition("{\"all\":[]}"), anyDeal)).isTrue();
            assertThat(evaluator.evaluate(condition("{\"any\":[]}"), anyDeal)).isFalse();
        }

        @Test
        @DisplayName("any matches when one branch holds")
        void anyMatches() throws Exception {
            Condition c = condition("""
                {"any":[{"field":"stage","op":"eq","value":"won"},
                        {"field":"stage","op":"eq","value":"negotiation"}]}""");

            assertThat(evaluator.evaluate(c, staleFor(1))).isTrue();
        }

        @Test
        @DisplayName("not inverts")
        void notInverts() throws Exception {
            Condition c = condition(
                    "{\"not\":{\"field\":\"stage\",\"op\":\"eq\",\"value\":\"won\"}}");

            assertThat(evaluator.evaluate(c, staleFor(1))).isTrue();
        }

        @Test
        @DisplayName("nests to arbitrary depth")
        void nesting() throws Exception {
            Condition c = condition("""
                {"all":[
                  {"any":[{"field":"stage","op":"eq","value":"negotiation"},
                          {"field":"stage","op":"eq","value":"proposal"}]},
                  {"not":{"field":"value","op":"lt","value":1000}}
                ]}""");

            assertThat(evaluator.evaluate(c, staleFor(1))).isTrue();
        }
    }

    @Nested
    @DisplayName("operators")
    class Operators {

        @Test
        @DisplayName("in and not_in work over string sets")
        void membership() throws Exception {
            DealFacts negotiation = staleFor(1);

            assertThat(evaluator.evaluate(
                    condition("{\"field\":\"stage\",\"op\":\"in\",\"value\":[\"proposal\",\"negotiation\"]}"),
                    negotiation)).isTrue();
            assertThat(evaluator.evaluate(
                    condition("{\"field\":\"stage\",\"op\":\"not_in\",\"value\":[\"won\",\"lost\"]}"),
                    negotiation)).isTrue();
        }

        @Test
        @DisplayName("money compares numerically, not lexically")
        void numericComparison() throws Exception {
            // "9" > "100000" as strings; the whole high-value rule depends on this.
            DealFacts bigDeal = deal("proposal", "100000.00", NOW, null);
            DealFacts smallDeal = deal("proposal", "9.00", NOW, null);

            Condition c = condition("{\"field\":\"value\",\"op\":\"gte\",\"value\":100000}");
            assertThat(evaluator.evaluate(c, bigDeal)).isTrue();
            assertThat(evaluator.evaluate(c, smallDeal)).isFalse();
        }

        @Test
        @DisplayName("a negative days-remaining means the close date has slipped")
        void closeDateSlipped() throws Exception {
            DealFacts slipped = deal("proposal", "1000", NOW, LocalDate.of(2026, 8, 1));
            DealFacts upcoming = deal("proposal", "1000", NOW, LocalDate.of(2026, 12, 1));

            Condition c = condition(
                    "{\"field\":\"expected_close_date_days_remaining\",\"op\":\"lt\",\"value\":0}");
            assertThat(evaluator.evaluate(c, slipped)).isTrue();
            assertThat(evaluator.evaluate(c, upcoming)).isFalse();
        }
    }

    @Nested
    @DisplayName("failing closed")
    class FailingClosed {

        @Test
        @DisplayName("an unknown fact throws rather than evaluating to false")
        void unknownFieldThrows() throws Exception {
            // Silently returning false would hide a typo forever; the engine
            // catches this and disables the rule with a recorded reason.
            assertThatThrownBy(() -> evaluator.evaluate(
                    condition("{\"field\":\"nonexistent\",\"op\":\"eq\",\"value\":1}"), staleFor(1)))
                    .isInstanceOf(UnknownFieldException.class)
                    .hasMessageContaining("nonexistent");
        }

        @Test
        @DisplayName("comparing a string with an ordering operator is rejected")
        void nonNumericOrdering() throws Exception {
            assertThatThrownBy(() -> evaluator.evaluate(
                    condition("{\"field\":\"stage\",\"op\":\"gt\",\"value\":5}"), staleFor(1)))
                    .isInstanceOf(IllegalArgumentException.class);
        }
    }

    @Nested
    @DisplayName("parsing")
    class Parsing {

        @Test
        @DisplayName("rejects an unknown operator")
        void unknownOperator() {
            assertThatThrownBy(() -> condition("{\"field\":\"stage\",\"op\":\"sorta_eq\",\"value\":1}"))
                    .isInstanceOf(IllegalArgumentException.class)
                    .hasMessageContaining("sorta_eq");
        }

        @Test
        @DisplayName("rejects a comparison with no value where one is required")
        void missingValue() {
            assertThatThrownBy(() -> condition("{\"field\":\"stage\",\"op\":\"eq\"}"))
                    .isInstanceOf(IllegalArgumentException.class);
        }

        @Test
        @DisplayName("requires an array for in / not_in")
        void membershipNeedsArray() {
            assertThatThrownBy(() -> condition("{\"field\":\"stage\",\"op\":\"in\",\"value\":\"won\"}"))
                    .isInstanceOf(IllegalArgumentException.class);
        }

        @Test
        @DisplayName("is_null needs no value")
        void isNullNeedsNoValue() throws Exception {
            assertThat(condition("{\"field\":\"score\",\"op\":\"is_null\"}")).isNotNull();
        }
    }

    @Nested
    @DisplayName("the seeded rules")
    class SeededRules {

        @Test
        @DisplayName("stale_negotiation fires on a genuinely stale negotiation")
        void staleNegotiation() throws Exception {
            Condition c = condition("""
                {"all":[{"op":"eq","field":"stage","value":"negotiation"},
                        {"op":"gte","field":"days_since_last_activity","value":14}]}""");

            assertThat(evaluator.evaluate(c, staleFor(21))).isTrue();
            assertThat(evaluator.evaluate(c, staleFor(3))).isFalse();
        }

        @Test
        @DisplayName("high_value_needs_attention needs all three clauses")
        void highValue() throws Exception {
            Condition c = condition("""
                {"all":[{"op":"gte","field":"value","value":100000},
                        {"op":"gte","field":"days_since_last_activity","value":7},
                        {"op":"in","field":"stage","value":["qualified","proposal","negotiation"]}]}""");

            DealFacts qualifies = deal("proposal", "150000", NOW.minusSeconds(86_400L * 10), null);
            DealFacts tooCheap = deal("proposal", "5000", NOW.minusSeconds(86_400L * 10), null);
            DealFacts tooRecent = deal("proposal", "150000", NOW.minusSeconds(86_400L * 2), null);
            DealFacts alreadyWon = deal("won", "150000", NOW.minusSeconds(86_400L * 10), null);

            assertThat(evaluator.evaluate(c, qualifies)).isTrue();
            assertThat(evaluator.evaluate(c, tooCheap)).isFalse();
            assertThat(evaluator.evaluate(c, tooRecent)).isFalse();
            assertThat(evaluator.evaluate(c, alreadyWon)).isFalse();
        }
    }
}
