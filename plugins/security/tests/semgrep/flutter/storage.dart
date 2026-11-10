const kTokenKey = 'k';

Future<void> save(SharedPreferences prefs, String token, String prefix) async {
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
  // ruleid: insecure-storage
  await prefs.setString('TOKEN_KEY', token);
  // ruleid: insecure-storage
  await prefs.setString('${prefix}_token', token);
  // ruleid: insecure-storage
  await prefs.setString('$prefix:token', token);
  // ok: insecure-storage
  await prefs.setString('tokenCount', '1');
  // ok: insecure-storage
  await prefs.setString('PASSWORDLESS_ENABLED', '1');
  // ok: insecure-storage
  await prefs.setString('last_token_refresh_at', '1');
}
