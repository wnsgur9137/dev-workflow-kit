import 'dart:io';

class DevOverrides extends HttpOverrides {
  @override
  HttpClient createHttpClient(SecurityContext? context) {
    // ruleid: bad-certificate-callback
    return super.createHttpClient(context)
      ..badCertificateCallback = (X509Certificate cert, String host, int port) => true;
  }
}

void block(HttpClient c) {
  // ruleid: bad-certificate-callback
  c.badCertificateCallback = (cert, host, port) { return true; };
  // ok: bad-certificate-callback
  c.badCertificateCallback = (cert, host, port) => host == 'dev.local';
}

void urls(Dio dio, String id, String base, String url) {
  // ruleid: insecure-http-url
  final a = Uri.parse('http://api.example.com/v1');
  // ruleid: insecure-http-url
  final b = Uri.parse('http://localhost.evil.com/x');
  // ruleid: insecure-http-url
  final c = Uri.parse('http://10.0.2.20/x');
  // ruleid: insecure-http-url
  final d = Uri.http('api.example.com', '/v1');
  // ruleid: insecure-http-url
  final e = Dio(BaseOptions(connectTimeout: t, baseUrl: 'http://api.example.com'));
  // ruleid: insecure-http-url
  dio.get('http://api.example.com/x');
  // ok: insecure-http-url
  final f = Uri.parse('http://localhost:8080');
  // ok: insecure-http-url
  final g = Uri.parse('http://10.0.2.2:3000/x');
  // ok: insecure-http-url
  final h = Uri.parse('http://127.0.0.1');
  // ok: insecure-http-url
  final i = Uri.http('localhost:8080', '/v1');
  // ok: insecure-http-url
  final j = Uri.parse('https://api.example.com');
  // ruleid: insecure-http-url
  final k = Uri.parse("http://api.example.com/$id");
  // ruleid: insecure-http-url
  final l = Uri.parse('http://api.example.com/${id}');
  // ok: insecure-http-url
  final m = Uri.parse('http://localhost:8080/$id');
  // ok: insecure-http-url
  final n = Uri.parse('$base/v1');
  // ok: insecure-http-url
  final o = Uri.parse(url);
}
