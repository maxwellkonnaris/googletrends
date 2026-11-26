# Covariance sign sensitivity: target, estimator and limits

## Target and observation

For aligned periods in one geography, let A_i be absolute searches for term i,
T total Google searches, and W_i=A_i/T the term's share. Write X=log W_i,
Y=log W_j and Z=log T. The target is the covariance of **log absolute search
counts**, Cov(X+Z,Y+Z), across the periods/population under consideration.
It is not covariance of unlogged counts, a regression effect or a health outcome.

Observed Trends indices are sampled, normalized, rounded and sometimes suppressed
proxies for W. [Google's data FAQ](https://support.google.com/trends/answer/4365533)
describes that normalization, low-volume zeros and statistical noise. The identity
below holds for idealized true shares. Its empirical application to processed
Trends indices is an approximation that requires sensitivity analysis.

## Pairwise bound

Let c=Cov(X,Y), s=SD(Z), b=SD(X+Y), and d=SD(X-Y). Then

```text
Cov(X+Z,Y+Z) = c + s² + Cov(X+Y,Z)
             ∈ [c+s²-s*b, c+s²+s*b]
```

The interval follows from Cauchy-Schwarz. With unrestricted dependence on Z,
each endpoint is attainable for that pair by making centered Z proportional to
plus/minus centered X+Y, with its prescribed standard deviation. Intermediate
covariances can be attained by an appropriate correlated/orthogonal combination.

Since d²=b²-4c, the zero-attainability band on the nonnegative s axis is

```text
lower = abs(b-d)/2
upper = (b+d)/2
```

Below the lower endpoint the sign agrees with c; between endpoints zero is
attainable; above the upper endpoint the covariance is positive. Endpoints allow
zero, not a strictly identified sign. Degenerate bands can collapse. Pairwise
extrema may require different Z series: this does not establish simultaneous
attainability of all pairwise extreme covariance values with one shared T.

## Estimator and uncertainty

The implementation substitutes sample covariance with denominator n-1 and sample
standard deviations into those expressions. Thus reported thresholds are **sample
plug-in sensitivity thresholds**, not population identification guarantees or
confidence limits. No total-search SD, rho, sampling standard error, temporal
correlation adjustment or confidence interval is estimated.

The descriptive between-pull SD of centered log indices is not a standard error
or confidence interval. Acquisition on different UTC days does not prove that
Google drew independent samples. Additional sampling behavior evidence is needed
before treating the number of pulls as an independent replicate count.

## Preprocessing assumptions

- All inputs to a pair describe the same geography, date grid and resolution.
- Each series is related to a positive share by an exact multiplicative constant
  for the scaling-invariance argument. Integer rounding, suppression and privacy
  noise violate that exact model.
- A complete-date rule excludes dates unavailable or partial in any term/pull in
  that region; results describe retained periods. Missingness can affect the target.
- Below-resolution observations are replaced by the assembly `--floor`, default
  0.5, before centering and geometric averaging. This replacement is an assumption
  about censored values, not an observation or censoring model.
- Before covariance, the conservative default screening rule drops terms with
  more than 10% raw below-resolution dates in any pull in the selected window.
  Raw masks, rather than rescaled averaged values, determine that screen.
- Constant/numerically zero-variance terms are removed; at least 20 selected dates
  and two varying terms are required. Twenty is a software guard, not a theorem
  establishing adequate statistical precision.

Exact positive per-term scaling shifts logs by constants, leaving covariance and
these thresholds unchanged. Log centering across complete matched dates removes
that constant; it does not correct measurement noise or censoring. Averaging may
smooth genuine temporal variation as well as sampling noise. Analyses on each
pull and on multiple replacement values should be compared before substantive claims.

## What would change the assessment

Reliable external information about total-search variation or its relationship
to term shares could narrow the unrestricted sensitivity set. Evidence about
Google's sampling dependence could justify or invalidate replicate-based uncertainty
calculations. Strong changes across replacement values, retention rules or single
pulls would weaken the interpretation of averaged-index results. Establishing a
wildfire/respiratory causal relationship requires a separate design with measured
exposure/outcomes and confounding assumptions; this tool does not supply it.
