/*
 * vec-audit — fixture de test : example.c
 * Contient des boucles qui couvrent les cas principaux de vectorisation.
 */
#include <stdlib.h>

/* Cas 1 : vectorisable (pas d'aliasing, borne connue, corps simple) */
void add_vectors(float * __restrict__ a,
                 float * __restrict__ b,
                 float * __restrict__ c,
                 int n)
{
    for (int i = 0; i < n; i++) {
        c[i] = a[i] + b[i];
    }
}

/* Cas 2 : aliasing potentiel — les pointeurs ne sont pas restrict */
void add_vectors_alias(float *a, float *b, float *c, int n)
{
    for (int i = 0; i < n; i++) {
        c[i] = a[i] + b[i];
    }
}

/* Cas 3 : control flow dans la boucle */
void threshold(float *a, float *b, int n)
{
    for (int i = 0; i < n; i++) {
        if (a[i] > 0.0f)
            b[i] = a[i] * 2.0f;
        else
            b[i] = 0.0f;
    }
}

/* Cas 4 : réduction (dot product) */
float dot_product(float *a, float *b, int n)
{
    float sum = 0.0f;
    for (int i = 0; i < n; i++) {
        sum += a[i] * b[i];
    }
    return sum;
}

/* Cas 5 : dépendance entre itérations */
void prefix_sum(float *a, int n)
{
    for (int i = 1; i < n; i++) {
        a[i] += a[i - 1];
    }
}
