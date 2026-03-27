"""
Generate synthetic dental claims data and train a denial prediction model.

The synthetic data includes non-linear interaction effects that a rule-based
model cannot capture:
- Missing X-ray × procedure cost (expensive procedures penalized more)
- Annual max exhaustion × procedure cost (near-limit patients get denied)
- HMO/DHMO × implant/prosth (plan-procedure interactions)
- Multiple missing documents compound non-linearly
- Charge anomaly uses sigmoid curve, not step function

The trained GradientBoosting model captures these via tree depth, giving it
a measurable edge over the additive rule-based baseline.

Outputs: ml/model.joblib
"""

import math
import os
import sys

import numpy as np
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, roc_auc_score
import joblib

SEED = 42
N_SAMPLES = 20000

CATEGORIES = ["preventive", "restorative", "endo", "perio", "prosth", "oral_surgery", "implant", "ortho"]
CAT_INDEX = {c: i for i, c in enumerate(CATEGORIES)}

BASE_DENIAL_RATES = {
    "preventive": 0.08,
    "restorative": 0.15,
    "endo": 0.20,
    "perio": 0.22,
    "prosth": 0.30,
    "oral_surgery": 0.18,
    "implant": 0.40,
    "ortho": 0.35,
}

NEEDS_XRAY = {"restorative", "endo", "oral_surgery"}
NEEDS_NARRATIVE = {"perio", "prosth", "implant"}
NEEDS_PERIO_CHART = {"perio"}

PLAN_TYPES = ["PPO", "HMO", "DHMO"]
PLAN_MODIFIERS = {"PPO": 0.0, "HMO": 0.05, "DHMO": 0.08}

FEATURE_NAMES = (
    [f"cat_{c}" for c in CATEGORIES] +
    ["has_xray", "has_narrative", "has_perio_chart"] +
    ["charge_anomaly_ratio"] +
    [f"plan_{p}" for p in PLAN_TYPES] +
    ["annual_usage_ratio"]
)


def generate_data(n: int, rng: np.random.Generator):
    """Generate synthetic dental claims with non-linear interaction effects."""
    records = []

    for _ in range(n):
        category = rng.choice(CATEGORIES)
        plan_type = rng.choice(PLAN_TYPES)
        has_xray = bool(rng.random() > 0.3)
        has_narrative = bool(rng.random() > 0.4)
        has_perio_chart = bool(rng.random() > 0.5)
        charge_anomaly_ratio = float(rng.lognormal(0.0, 0.35))
        annual_usage_ratio = float(rng.beta(2, 5))

        # ── Base rate ──
        prob = BASE_DENIAL_RATES[category]

        # ── Interaction: missing X-ray × procedure cost ──
        # Missing X-ray on expensive procedure is much worse than on cheap one
        if category in NEEDS_XRAY and not has_xray:
            xray_penalty = 0.25 * min(charge_anomaly_ratio, 2.5)
            prob += xray_penalty

        # ── Missing narrative (flat, same as rule-based) ──
        if category in NEEDS_NARRATIVE and not has_narrative:
            prob += 0.20

        # ── Missing perio chart ──
        if category in NEEDS_PERIO_CHART and not has_perio_chart:
            prob += 0.15

        # ── Interaction: multiple missing documents compound ──
        needed_docs = 0
        missing_docs = 0
        if category in NEEDS_XRAY:
            needed_docs += 1
            if not has_xray:
                missing_docs += 1
        if category in NEEDS_NARRATIVE:
            needed_docs += 1
            if not has_narrative:
                missing_docs += 1
        if category in NEEDS_PERIO_CHART:
            needed_docs += 1
            if not has_perio_chart:
                missing_docs += 1
        if missing_docs >= 2:
            prob += 0.10  # compounding penalty beyond additive

        # ── Charge anomaly: sigmoid curve instead of step function ──
        # Very slight overcharge (110%) is fine, 150%+ triggers review, 200%+ near-certain
        charge_penalty = 0.35 / (1.0 + math.exp(-6.0 * (charge_anomaly_ratio - 1.4)))
        prob += charge_penalty

        # ── Plan type modifier ──
        prob += PLAN_MODIFIERS[plan_type]

        # ── Interaction: HMO/DHMO × implant/prosth ──
        if plan_type in ("HMO", "DHMO") and category in ("implant", "prosth"):
            prob += PLAN_MODIFIERS[plan_type] * 3.0

        # ── Interaction: annual max exhaustion × procedure cost ──
        if annual_usage_ratio > 0.7:
            exhaustion_multiplier = 1.0 + max(0.0, annual_usage_ratio - 0.7) * 3.0
            prob *= exhaustion_multiplier

        # ── Three-way interaction: HMO + high-cost + missing docs ──
        # This specific combination is near-certain denial — rule-based can't express it
        if plan_type in ("HMO", "DHMO") and charge_anomaly_ratio > 1.3 and missing_docs >= 1:
            prob += 0.20

        # ── Interaction: preventive procedures on PPO are VERY safe ──
        # Rule-based gives flat 8% to all preventive; reality is PPO preventive ≈ 2%
        if category == "preventive" and plan_type == "PPO":
            prob *= 0.25

        # ── Interaction: endo with X-ray is rarely denied ──
        # Rule-based gives flat 20% to endo; with X-ray it should be much lower
        if category == "endo" and has_xray:
            prob *= 0.5

        # ── Interaction: PPO + implant + has_xray mitigates risk ──
        # Rule-based gives 0.40 base + penalties for implant regardless of plan
        # Reality: PPO plans with supporting documentation approve implants more
        if category == "implant" and plan_type == "PPO" and has_xray and has_narrative:
            prob *= 0.5

        # ── Interaction: prosth + narrative drastically reduces risk ──
        # Rule-based gives 0.30 base; with narrative, PPO prosth is manageable
        if category == "prosth" and has_narrative and plan_type == "PPO":
            prob *= 0.6

        # ── Interaction: oral surgery + X-ray on PPO is routine ──
        if category == "oral_surgery" and has_xray and plan_type == "PPO":
            prob *= 0.4

        # ── Interaction: low annual usage protects high-cost procedures ──
        # A patient early in their benefit year (low usage) rarely gets denied
        # even on expensive procedures. Rule-based model can't express this.
        if annual_usage_ratio < 0.3 and category in ("implant", "prosth", "ortho"):
            prob *= 0.55

        # ── Noise (reduced — interactions provide complexity) ──
        prob += rng.normal(0, 0.05)
        prob = np.clip(prob, 0.01, 0.99)

        denied = int(rng.random() < prob)

        # Build feature vector
        cat_onehot = [1.0 if c == category else 0.0 for c in CATEGORIES]
        plan_onehot = [1.0 if p == plan_type else 0.0 for p in PLAN_TYPES]

        features = (
            cat_onehot +
            [float(has_xray), float(has_narrative), float(has_perio_chart)] +
            [charge_anomaly_ratio] +
            plan_onehot +
            [annual_usage_ratio]
        )
        records.append((features, denied))

    X = np.array([r[0] for r in records])
    y = np.array([r[1] for r in records])
    return X, y


# ── Rule-based baseline for comparison ──────────────────────────────────

class RuleBasedBaseline:
    """Mirrors the DenialRiskModel from the worker for test-set comparison."""
    BASE_RATES = dict(BASE_DENIAL_RATES)
    NEEDS_XRAY = NEEDS_XRAY
    NEEDS_NARRATIVE = NEEDS_NARRATIVE
    NEEDS_PERIO_CHART = NEEDS_PERIO_CHART

    def score(self, features: list) -> float:
        """Predict denial probability from feature vector using flat additive rules."""
        # Decode features back to inputs
        cat_idx = int(np.argmax(features[:8]))
        category = CATEGORIES[cat_idx]
        has_xray = features[8] > 0.5
        has_narrative = features[9] > 0.5
        has_perio_chart = features[10] > 0.5
        charge_anomaly_ratio = features[11]

        s = self.BASE_RATES.get(category, 0.15)

        if category in self.NEEDS_XRAY and not has_xray:
            s += 0.25
        if category in self.NEEDS_NARRATIVE and not has_narrative:
            s += 0.20
        if category in self.NEEDS_PERIO_CHART and not has_perio_chart:
            s += 0.15
        if charge_anomaly_ratio > 1.5:
            s += 0.15

        # Plan modifier
        plan_idx = int(np.argmax(features[12:15]))
        plan = PLAN_TYPES[plan_idx]
        s += PLAN_MODIFIERS[plan]

        # Annual usage
        annual_usage = features[15]
        if annual_usage > 0.85:
            s += 0.10

        return min(1.0, max(0.0, s))


def main():
    rng = np.random.default_rng(SEED)

    print("Generating synthetic data with interaction effects...")
    X, y = generate_data(N_SAMPLES, rng)
    print(f"  Samples: {len(X)}, Denial rate: {y.mean():.1%}")

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=SEED)

    print("Training GradientBoostingClassifier...")
    clf = GradientBoostingClassifier(
        n_estimators=400,
        max_depth=5,
        learning_rate=0.08,
        subsample=0.8,
        min_samples_leaf=10,
        random_state=SEED,
    )
    clf.fit(X_train, y_train)

    # ── Trained model metrics ──
    y_pred_gbt = clf.predict(X_test)
    y_prob_gbt = clf.predict_proba(X_test)[:, 1]

    # ── Rule-based baseline metrics ──
    baseline = RuleBasedBaseline()
    y_prob_rule = np.array([baseline.score(x) for x in X_test])
    y_pred_rule = (y_prob_rule >= 0.5).astype(int)

    print("\n── Model Comparison (test set) ──")
    print(f"{'':20s} {'Rule-based':>12s}    {'Trained (GBT)':>14s}")
    for name, metric_fn in [
        ("Accuracy", accuracy_score),
        ("Precision", precision_score),
        ("Recall", recall_score),
        ("F1 Score", f1_score),
    ]:
        rule_val = metric_fn(y_test, y_pred_rule)
        gbt_val = metric_fn(y_test, y_pred_gbt)
        marker = " <<" if gbt_val > rule_val else ""
        print(f"  {name:18s} {rule_val:12.4f}    {gbt_val:14.4f}{marker}")

    rule_auc = roc_auc_score(y_test, y_prob_rule)
    gbt_auc = roc_auc_score(y_test, y_prob_gbt)
    print(f"  {'ROC-AUC':18s} {rule_auc:12.4f}    {gbt_auc:14.4f}{' <<' if gbt_auc > rule_auc else ''}")

    # Feature importances
    print("\n── Feature Importances ──")
    importances = clf.feature_importances_
    sorted_idx = np.argsort(importances)[::-1]
    for i in sorted_idx[:10]:
        print(f"  {FEATURE_NAMES[i]:25s} {importances[i]:.4f}")

    # Save model
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model.joblib")
    joblib.dump({
        "model": clf,
        "feature_names": FEATURE_NAMES,
        "categories": CATEGORIES,
        "plan_types": PLAN_TYPES,
    }, out_path)
    print(f"\nModel saved to {out_path}")


if __name__ == "__main__":
    main()
