# Domain Context: Data Science

## Core Principles
- Reproducibility: all experiments must be reproducible from code + data + environment
- Data integrity: source data is never mutated; transformations are versioned
- Experiment tracking: every model training run is logged with parameters and metrics
- Bias awareness: actively test for and document bias in training data and model outputs

## Quality Standards
- Train/validation/test split must be established before model development
- Baseline model required before complex model development (know what you're improving on)
- Model performance reported on held-out test set, not training or validation
- Feature engineering documented and reviewed before production use
- Model cards: document model purpose, training data, limitations, and fairness considerations

## Common Risks
- Data leakage: test data information leaking into training (train/test contamination)
- Distribution shift: model trained on historical data that no longer reflects current patterns
- Label quality: ground truth labels with errors or inconsistent definitions
- Overfit to validation set through repeated hyperparameter tuning
- Missing data: unhandled nulls or inconsistent representations can silently corrupt results
- Class imbalance: model optimizes for majority class at the expense of minority class

## Best Practices
- Version control for data (DVC), code (git), and models (MLflow, W&B)
- Pipeline orchestration (Airflow, Prefect) for production data workflows
- Data quality checks (Great Expectations, dbt tests) in data pipelines
- Model monitoring: track prediction drift and data drift in production
- A/B testing framework before full model deployment
- Feature stores for reusable, consistent feature computation

## Prior Art
- Cross-validation for reliable performance estimation on small datasets
- Ensemble methods (Random Forest, Gradient Boosting) as strong baselines
- SHAP / LIME for model explainability
- Confusion matrix, ROC-AUC, PR curve for classification evaluation
- RMSE, MAE, MAPE for regression evaluation
