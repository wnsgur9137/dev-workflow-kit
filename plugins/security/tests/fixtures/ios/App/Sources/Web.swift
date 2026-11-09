import WebKit

func makeWebView() -> WKWebView {
    let config = WKWebViewConfiguration()
    config.preferences.setValue(true, forKey: "allowFileAccessFromFileURLs")
    return WKWebView(frame: .zero, configuration: config)
}
