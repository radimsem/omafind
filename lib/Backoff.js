.pragma library

function delay(failures) {
  return Math.min(2000, 200 * failures)
}
