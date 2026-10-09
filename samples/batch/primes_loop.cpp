// Time Limit Exceeded: never finishes (volatile, so the compiler cannot remove the loop).
#include <bits/stdc++.h>
using namespace std;

int32_t main() {
    cin.tie(0); ios::sync_with_stdio(0);
    volatile long long x = 0;
    while (true) x++;
    return 0;
}
