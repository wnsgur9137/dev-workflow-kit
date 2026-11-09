function render() {
  const name = new URLSearchParams(location.search).get("name");
  document.getElementById("greeting").innerHTML = "Hello " + name;
  document.write(location.hash);
}
