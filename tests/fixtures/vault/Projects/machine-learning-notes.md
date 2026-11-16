---
title: "Machine Learning Fundamentals"
tags: [ml, fundamentals, learning]
created: 2024-01-15
updated: 2024-01-20
---

# Machine Learning Fundamentals

Core concepts and terminology for machine learning.

## Supervised Learning

Supervised learning uses labeled data to train models.

### Classification

Classification predicts discrete categories.

```python
from sklearn.linear_model import LogisticRegression
model = LogisticRegression()
model.fit(X_train, y_train)
```

### Regression

Regression predicts continuous values.

## Unsupervised Learning

Unsupervised learning finds patterns in unlabeled data.

### Clustering

Grouping similar data points together.

### Dimensionality Reduction

Reducing feature count while preserving information.

## Model Evaluation

Key metrics for assessing model performance.

- Accuracy
- Precision
- Recall
- F1 Score
- AUC-ROC