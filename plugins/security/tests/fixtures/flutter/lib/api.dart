import 'dart:io';
import 'package:shared_preferences/shared_preferences.dart';

class DevOverrides extends HttpOverrides {
  @override
  HttpClient createHttpClient(SecurityContext? context) {
    return super.createHttpClient(context)
      ..badCertificateCallback = (X509Certificate cert, String host, int port) => true;
  }
}

Future<void> saveSession(String token) async {
  final prefs = await SharedPreferences.getInstance();
  await prefs.setString('access_token', token);
  await prefs.setBool('onboarded', true);
}

final legacyApi = Uri.parse('http://api.example.com/v1');
final localApi = Uri.parse('http://localhost:8080');
