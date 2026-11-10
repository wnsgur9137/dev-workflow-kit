// 음성 사례 — 기준선 must_not_find (이 파일에서는 아무것도 잡히면 안 된다)
import 'package:shared_preferences/shared_preferences.dart';

Future<void> savePrefs(String lang) async {
  final prefs = await SharedPreferences.getInstance();
  await prefs.setBool('onboarded', true);
  await prefs.setString('tokenizer_lang', lang);
}

final localApi = Uri.parse('http://localhost:8080');
final emulatorApi = Uri.parse('http://10.0.2.2:3000/v1');
final secureApi = Uri.parse('https://api.example.com/v1');
