// Runtime Error with a message on stderr: vector::at() throws std::out_of_range.
#include <bits/stdc++.h>
using namespace std;

int32_t main() {
    cin.tie(0); ios::sync_with_stdio(0);
    int n;
    cin >> n;
    vector<int> v(10);
    cout << v.at(n) << '\n';                 // n = 20 in sample 1: out of range
    return 0;
}
