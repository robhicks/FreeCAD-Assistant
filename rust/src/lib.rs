use pyo3::prelude::*;

mod plan_parser;

use plan_parser::{Plan, PlanStep};

#[pymodule]
fn freecad_assistant_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PlanStep>()?;
    m.add_class::<Plan>()?;
    m.add_function(wrap_pyfunction!(plan_parser::parse_response, m)?)?;
    m.add_function(wrap_pyfunction!(plan_parser::extract_code_block, m)?)?;
    Ok(())
}
