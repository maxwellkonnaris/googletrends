test_that("setup is explicit and pins the Python backend", {
  testthat::local_envvar(RETICULATE_PYTHON = NA)
  installed <- selected <- created <- NULL
  testthat::local_mocked_bindings(
    py_available = function(initialize) FALSE,
    virtualenv_exists = function(envname) FALSE,
    virtualenv_create = function(envname, python) created <<- python,
    py_install = function(packages, envname, method, pip) {
      installed <<- list(packages = packages, envname = envname, method = method, pip = pip)
    },
    use_virtualenv = function(virtualenv, required) selected <<- virtualenv,
    use_condaenv = function(condaenv, required) selected <<- condaenv,
    .package = "reticulate"
  )
  expect_identical(install_backend(method = "virtualenv", python = "/chosen/python"), "r-trendspull")
  expect_identical(created, "/chosen/python")
  expect_identical(selected, "r-trendspull")
  expect_true(installed$pip)
  expect_match(installed$packages, "googletrends.git@[0-9a-f]+$")
})

test_that("setup refuses to change an initialized Python session", {
  testthat::local_mocked_bindings(py_available = function(initialize) TRUE, .package = "reticulate")
  expect_error(install_backend(), "Restart R")
})

test_that("setup does not silently lose to a forced interpreter", {
  testthat::local_envvar(RETICULATE_PYTHON = "/already/configured/python")
  testthat::local_mocked_bindings(py_available = function(initialize) FALSE, .package = "reticulate")
  expect_error(install_backend(), "Unset RETICULATE_PYTHON")
})
