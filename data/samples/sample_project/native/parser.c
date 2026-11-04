#include <ctype.h>
#include <string.h>

/* Parse a signed integer; returns 0 on success, -1 on error. */
int parse_int(const char *s, int *out) {
    int sign = 1, value = 0;
    if (s == NULL || out == NULL) return -1;
    while (isspace((unsigned char)*s)) s++;
    if (*s == '-' || *s == '+') {
        if (*s == '-') sign = -1;
        s++;
    }
    if (!isdigit((unsigned char)*s)) return -1;
    while (isdigit((unsigned char)*s)) {
        value = value * 10 + (*s - '0');
        s++;
    }
    *out = sign * value;
    return 0;
}
