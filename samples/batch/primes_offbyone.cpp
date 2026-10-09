// Wrong Answer: off by one, misses the pair whose q is exactly N (sample 2: N = 7).
#include <bits/stdc++.h>
using namespace std;

int32_t main() {
    cin.tie(0); ios::sync_with_stdio(0);
    int n;
    cin >> n;
    vector<bool> prime(n + 1, true);
    prime[0] = prime[1] = false;
    for (int i = 2; (long long)i * i <= n; i++)
        if (prime[i])
            for (int j = i * i; j <= n; j += i) prime[j] = false;
    for (int d : {2, 4, 6}) {
        int cnt = 0, last = -1;
        for (int p = 2; p + d < n; p++)
            if (prime[p] && prime[p + d]) cnt++, last = p;
        if (cnt) cout << cnt << ' ' << last << ' ' << last + d << '\n';
        else cout << "0 -\n";
    }
    return 0;
}
