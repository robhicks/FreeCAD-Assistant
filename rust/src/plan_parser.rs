use std::sync::LazyLock;

use pyo3::prelude::*;
use regex::Regex;

static PLAN_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?s)<<<PLAN>>>\s*(.*?)\s*<<<END_PLAN>>>").unwrap());

static STEP_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?i)STEP\s+(\d+)\s*:\s*(.+)").unwrap());

static CODE_BLOCK_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?s)```python\s*\n(.*?)```").unwrap());

#[pyclass]
pub struct PlanStep {
    #[pyo3(get, set)]
    pub number: i32,
    #[pyo3(get, set)]
    pub description: String,
    #[pyo3(get, set)]
    pub status: String,
    #[pyo3(get, set)]
    pub code: Option<String>,
    #[pyo3(get, set)]
    pub result: Option<PyObject>,
    #[pyo3(get, set)]
    pub retries: i32,
}

#[pymethods]
impl PlanStep {
    #[new]
    fn new(number: i32, description: String) -> Self {
        PlanStep {
            number,
            description,
            status: "pending".to_string(),
            code: None,
            result: None,
            retries: 0,
        }
    }
}

#[pyclass]
pub struct Plan {
    #[pyo3(get, set)]
    pub steps: Vec<Py<PlanStep>>,
    #[pyo3(get, set)]
    pub raw_text: String,
}

#[pymethods]
impl Plan {
    #[new]
    fn new(steps: Vec<Py<PlanStep>>, raw_text: String) -> Self {
        Plan { steps, raw_text }
    }
}

#[pyfunction]
pub fn parse_response(
    py: Python<'_>,
    text: &str,
) -> PyResult<(Option<Py<Plan>>, String)> {
    let m = match PLAN_RE.captures(text) {
        Some(caps) => caps,
        None => return Ok((None, text.to_string())),
    };

    let full_match = m.get(0).unwrap();
    let preamble = text[..full_match.start()].trim().to_string();
    let plan_body = m.get(1).unwrap().as_str();

    let mut steps: Vec<Py<PlanStep>> = Vec::new();
    for step_match in STEP_RE.captures_iter(plan_body) {
        let number: i32 = step_match
            .get(1)
            .unwrap()
            .as_str()
            .parse()
            .unwrap_or(0);
        let description = step_match.get(2).unwrap().as_str().trim().to_string();
        let step = PlanStep::new(number, description);
        steps.push(Py::new(py, step)?);
    }

    if steps.is_empty() {
        return Ok((None, text.to_string()));
    }

    let plan = Plan {
        steps,
        raw_text: plan_body.to_string(),
    };
    Ok((Some(Py::new(py, plan)?), preamble))
}

#[pyfunction]
pub fn extract_code_block(text: &str) -> Option<String> {
    CODE_BLOCK_RE.captures(text).map(|caps| {
        caps.get(1)
            .unwrap()
            .as_str()
            .trim_end_matches('\n')
            .to_string()
    })
}
