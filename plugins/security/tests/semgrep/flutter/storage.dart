const kTokenKey = 'k';

Future<void> save(SharedPreferences prefs, String token) async {
  // ruleid: insecure-storage
  await prefs.setString('access_token', token);
  // ruleid: insecure-storage
  await prefs.setString(kTokenKey, token);
  // ruleid: insecure-storage
  await prefs.setString(Keys.userPassword, token);
  // ok: insecure-storage
  await prefs.setString('tokenizer_lang', 'ko');
  // ok: insecure-storage
  await prefs.setString(tokenizerLang, 'ko');
  // ok: insecure-storage
  await prefs.setString('theme', 'dark');
}
