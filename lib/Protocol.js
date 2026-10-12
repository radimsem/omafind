.pragma library

function encode(obj) {
  return JSON.stringify(obj) + "\n"
}

function decode(line) {
  try {
    var value = JSON.parse(line)
    return value && typeof value === "object" && !Array.isArray(value)
      && value.v === 1 ? value : null
  } catch (error) {
    return null
  }
}

function hello() {
  return {t: "hello", v: 1}
}
