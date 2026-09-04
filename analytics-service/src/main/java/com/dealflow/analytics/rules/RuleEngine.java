package com.dealflow.analytics.rules;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.Clock;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * Evaluates every enabled rule against every deal and reconciles the findings.
 *
 * <p><b>Reconciliation, not accumulation.</b> Each sweep opens findings that are
 * newly true and resolves ones that no longer are, so the open finding set is a
 * pure function of current state. An append-per-run design would produce 24 rows
 * a day for one stuck deal and no way to tell when it recovered.
 */
@Service
public class RuleEngine {

    private static final Logger log = LoggerFactory.getLogger(RuleEngine.class);

    private final RuleRepository repository;
    private final RuleEvaluator evaluator = new RuleEvaluator();
    private final ObjectMapper objectMapper;
    private final Clock clock;

    public RuleEngine(RuleRepository repository, ObjectMapper objectMapper, Clock clock) {
        this.repository = repository;
        this.objectMapper = objectMapper;
        this.clock = clock;
    }

    public record RunSummary(
            String ruleCode, int evaluated, int opened, int resolved, String error) {}

    @Transactional
    public List<RunSummary> runAll() {
        List<DealFacts> facts = repository.facts(clock);
        List<RunSummary> summaries = new ArrayList<>();
        for (RuleDefinition rule : repository.enabled()) {
            summaries.add(run(rule, facts));
        }
        return summaries;
    }

    private RunSummary run(RuleDefinition rule, List<DealFacts> facts) {
        long runId = repository.startRun(rule.id());

        Condition condition;
        try {
            condition = ConditionParser.parse(rule.condition());
            repository.recordValidationError(rule.id(), null);
        } catch (RuntimeException e) {
            // A malformed rule is recorded and skipped, never guessed at.
            String message = "Invalid condition: " + e.getMessage();
            log.error("Rule '{}' is not evaluable: {}", rule.code(), message);
            repository.recordValidationError(rule.id(), message);
            repository.finishRun(runId, 0, 0, 0, message);
            return new RunSummary(rule.code(), 0, 0, 0, message);
        }

        List<Long> firing = new ArrayList<>();
        int opened = 0;
        int evaluated = 0;

        for (DealFacts deal : facts) {
            boolean matched;
            try {
                matched = evaluator.evaluate(condition, deal);
                evaluated++;
            } catch (UnknownFieldException e) {
                // Fail closed: a rule that cannot be evaluated does not fire.
                log.error("Rule '{}' references {}; not firing", rule.code(), e.getMessage());
                repository.recordValidationError(rule.id(), e.getMessage());
                repository.finishRun(runId, evaluated, opened, 0, e.getMessage());
                return new RunSummary(rule.code(), evaluated, opened, 0, e.getMessage());
            } catch (RuntimeException e) {
                log.error("Rule '{}' failed on deal {}: {}", rule.code(), deal.dealId(),
                        e.getMessage());
                continue;
            }

            if (matched) {
                firing.add(deal.dealId());
                if (repository.openFinding(rule.id(), deal.dealId(), detail(deal))) {
                    opened++;
                }
            }
        }

        int resolved = repository.resolveFindings(rule.id(), firing);
        repository.finishRun(runId, evaluated, opened, resolved, null);
        return new RunSummary(rule.code(), evaluated, opened, resolved, null);
    }

    /** Why this deal matched, so a finding is actionable without re-deriving it. */
    private String detail(DealFacts deal) {
        try {
            return objectMapper.writeValueAsString(Map.of(
                    "stage", String.valueOf(deal.values().get(DealFacts.STAGE)),
                    "value", String.valueOf(deal.values().get(DealFacts.VALUE)),
                    "daysSinceLastActivity",
                            String.valueOf(deal.values().get(DealFacts.DAYS_SINCE_LAST_ACTIVITY)),
                    "daysRemaining",
                            String.valueOf(deal.values().get(DealFacts.DAYS_REMAINING))));
        } catch (Exception e) {
            return "{}";
        }
    }
}
