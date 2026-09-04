package com.dealflow.analytics.rules;

import com.fasterxml.jackson.databind.JsonNode;
import java.math.BigDecimal;
import java.util.Objects;

/**
 * Evaluates a condition tree against one deal's facts. Pure: no Spring, no
 * database, no clock of its own -- everything time-dependent was already resolved
 * into {@link DealFacts}.
 *
 * <p><b>Null semantics, stated once because this is where rules engines go
 * quietly wrong:</b> a comparison against a null fact is FALSE for every operator
 * except {@code is_null}. Not null, not an error, not "unknown" -- false. So a
 * rule looking for deals older than 14 days does not fire on a deal whose
 * activity date is missing.
 */
public final class RuleEvaluator {

    public boolean evaluate(Condition condition, DealFacts facts) {
        return switch (condition) {
            case Condition.All all -> all.conditions().stream()
                    .allMatch(c -> evaluate(c, facts));
            case Condition.Any any -> any.conditions().stream()
                    .anyMatch(c -> evaluate(c, facts));
            case Condition.Not not -> !evaluate(not.condition(), facts);
            case Condition.Comparison comparison -> compare(comparison, facts);
        };
    }

    private boolean compare(Condition.Comparison comparison, DealFacts facts) {
        // Throws UnknownFieldException for an unknown fact, which the engine turns
        // into "this rule does not fire" -- fail closed, never open.
        Object fact = facts.get(comparison.field());

        if (comparison.operator() == Operator.IS_NULL) {
            return fact == null;
        }
        if (comparison.operator() == Operator.NOT_NULL) {
            return fact != null;
        }
        if (fact == null) {
            return false;
        }

        JsonNode value = comparison.value();
        return switch (comparison.operator()) {
            case EQ -> matches(fact, value);
            case NEQ -> !matches(fact, value);
            case IN -> anyMatches(fact, value);
            case NOT_IN -> !anyMatches(fact, value);
            case GT -> numeric(fact, value) > 0;
            case GTE -> numeric(fact, value) >= 0;
            case LT -> numeric(fact, value) < 0;
            case LTE -> numeric(fact, value) <= 0;
            case IS_NULL, NOT_NULL -> throw new IllegalStateException("handled above");
        };
    }

    private boolean anyMatches(Object fact, JsonNode array) {
        for (JsonNode element : array) {
            if (matches(fact, element)) {
                return true;
            }
        }
        return false;
    }

    /** Equality compares numerically when both sides are numbers, textually otherwise. */
    private boolean matches(Object fact, JsonNode value) {
        if (value.isNumber() && fact instanceof Number) {
            return toBigDecimal(fact).compareTo(value.decimalValue()) == 0;
        }
        if (value.isBoolean() && fact instanceof Boolean bool) {
            return bool == value.asBoolean();
        }
        return Objects.equals(String.valueOf(fact), value.asText());
    }

    /**
     * @return fact compared to value, as {@link Comparable#compareTo}
     * @throws IllegalArgumentException when either side is not numeric -- a
     *     misconfigured rule, surfaced rather than silently returning false
     */
    private int numeric(Object fact, JsonNode value) {
        if (!(fact instanceof Number) || !value.isNumber()) {
            throw new IllegalArgumentException(
                    "Ordering comparison needs numbers on both sides, got "
                            + fact.getClass().getSimpleName() + " and " + value.getNodeType());
        }
        return toBigDecimal(fact).compareTo(value.decimalValue());
    }

    private BigDecimal toBigDecimal(Object fact) {
        if (fact instanceof BigDecimal decimal) {
            return decimal;
        }
        return new BigDecimal(String.valueOf(fact));
    }
}
