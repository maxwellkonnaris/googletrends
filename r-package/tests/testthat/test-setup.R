test_that("setup is explicit and pins the Python backend", {
  installed <- selected <- NULL
  testthat::local_mocked_bindings(
    py_available = function(initialize) FALSE,
    py_install = function(packages, envname, method, pip) {
      installed <<- list(packages = packages, envname = envname, method = method, pip = pip)
    },
    use_virtualenv = function(virtualenv, required) selected <<- virtualenv,
    use_condaenv = function(condaenv, required) selected <<- condaenv,
    .package = "reticulate"
  )
  expect_identical(install_backend(), "r-trendspull")
  expect_identical(selected, "r-trendspull")
  expect_true(installed$pip)
  expect_match(installed$packages, "googletrends.git@[0-9a-f]+$")
})

test_that("setup refuses to change an initialized Python session", {
  testthat::local_mocked_bindings(py_available = function(initialize) TRUE, .package = "reticulate")
  expect_error(install_backend(), "Restart R")
})
