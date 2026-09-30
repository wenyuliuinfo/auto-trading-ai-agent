"use client";

import { Plus } from "lucide-react";
import { FormEvent, useState } from "react";

import { api, Theme, ThemeCreateRequest } from "@/lib/api";

interface ThemeFormProps {
  availableSubExposures: string[];
  onCreated: (theme: Theme) => void;
}

const MIN_SUB_EXPOSURES = 3;
const MAX_SUB_EXPOSURES = 6;

export function ThemeForm({
  availableSubExposures,
  onCreated,
}: ThemeFormProps) {
  const [name, setName] = useState("");
  const [definition, setDefinition] = useState("");
  const [subExposures, setSubExposures] = useState<string[]>([]);
  const [weightingScheme, setWeightingScheme] = useState<
    "equal_weight" | "score_weighted"
  >("equal_weight");
  const [validatorEnabled, setValidatorEnabled] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function toggleSubExposure(subExposure: string) {
    setSubExposures((current) => {
      if (current.includes(subExposure)) {
        return current.filter((item) => item !== subExposure);
      }
      if (current.length >= MAX_SUB_EXPOSURES) {
        return current;
      }
      return [...current, subExposure];
    });
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (subExposures.length < MIN_SUB_EXPOSURES) {
      setError(`Select at least ${MIN_SUB_EXPOSURES} sub-exposures.`);
      return;
    }
    const payload: ThemeCreateRequest = {
      name,
      definition,
      sub_exposures: subExposures,
      weighting_scheme: weightingScheme,
      validator_enabled: validatorEnabled,
    };
    setSubmitting(true);
    setError(null);
    try {
      const theme = await api.createTheme(payload);
      onCreated(theme);
      setName("");
      setDefinition("");
      setSubExposures([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Creation failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="panel panel-pad" onSubmit={handleSubmit}>
      <div className="panel-heading">
        <div className="icon-box">
          <Plus size={15} aria-hidden />
        </div>
        <div className="panel-title">New theme</div>
      </div>
      <div className="field-row">
        <label className="label" htmlFor="theme-name">
          Name
        </label>
        <input
          id="theme-name"
          className="field"
          value={name}
          onChange={(event) => setName(event.target.value)}
          required
        />
      </div>
      <div className="field-row">
        <label className="label" htmlFor="theme-definition">
          Definition
        </label>
        <textarea
          id="theme-definition"
          className="field"
          rows={3}
          value={definition}
          onChange={(event) => setDefinition(event.target.value)}
          required
        />
      </div>
      <div className="field-row">
        <div className="label sub-exposure-label">
          Sub-exposures
          <span className="sub-exposure-count">
            {subExposures.length}/{MAX_SUB_EXPOSURES}
          </span>
        </div>
        {availableSubExposures.length === 0 ? (
          <div className="form-error" role="alert">
            No sub-exposures are available.
          </div>
        ) : (
          <div className="sub-exposure-grid">
            {availableSubExposures.map((subExposure) => {
              const checked = subExposures.includes(subExposure);
              const disabled =
                !checked && subExposures.length >= MAX_SUB_EXPOSURES;
              return (
                <label
                  key={subExposure}
                  className={`sub-exposure-option${disabled ? " sub-exposure-option-disabled" : ""}`}
                >
                  <input
                    type="checkbox"
                    className="checkbox"
                    checked={checked}
                    disabled={disabled}
                    onChange={() => toggleSubExposure(subExposure)}
                  />
                  <span>{subExposure}</span>
                </label>
              );
            })}
          </div>
        )}
      </div>
      <div className="form-grid-2" style={{ marginBottom: "0.8rem" }}>
        <div>
          <label className="label" htmlFor="theme-weighting">
            Weighting scheme
          </label>
          <select
            id="theme-weighting"
            className="field"
            value={weightingScheme}
            onChange={(event) =>
              setWeightingScheme(event.target.value as "equal_weight" | "score_weighted")
            }
          >
            <option value="equal_weight">Equal weight</option>
            <option value="score_weighted">Score weighted</option>
          </select>
        </div>
        <div className="check-row">
          <label className="check-label" htmlFor="theme-validator">
            <input
              id="theme-validator"
              type="checkbox"
              className="checkbox"
              checked={validatorEnabled}
              onChange={(event) => setValidatorEnabled(event.target.checked)}
            />
            Validator
          </label>
        </div>
      </div>
      {error ? (
        <div className="form-error" role="alert">
          {error}
        </div>
      ) : null}
      <button className="btn btn-primary" type="submit" disabled={submitting}>
        <Plus size={16} aria-hidden />
        Create theme
      </button>
    </form>
  );
}
