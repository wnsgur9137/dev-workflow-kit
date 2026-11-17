#include <stdio.h>
#include <string.h>
static const char *aws = "@@AWS_KEY@@";
static const char *url = "http://api.example.com/v1/login";
int main(int argc, char **argv) { char buf[16]; strcpy(buf, argv[0]); printf("%s %s %s\n", aws, url, buf); return 0; }
