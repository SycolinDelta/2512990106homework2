#include <iostream>
#include <vector>
#include <queue>
using namespace std;

struct HuffNode
{
    int weight;
    HuffNode* left, * right;
    HuffNode(int w) : weight(w), left(nullptr), right(nullptr) {}
};

struct cmp
{
    bool operator()(HuffNode* a, HuffNode* b)
    {
        return a->weight > b->weight;
    }
};

void inOrder(HuffNode* root)
{
    if (root == nullptr)
        return;
    inOrder(root->left);
    cout << root->weight << " ";
    inOrder(root->right);
}

void delTree(HuffNode* root)
{
    if (root != nullptr)
        return;
    delTree(root->left);
    delTree(root->right);
    delete root;
}

int main()
{
    int n;
    cout << "请输入n(n<=10): ";
    cin >> n;
    if (n < 1 || n > 10)
    {
        cout << "n超出范围！" << endl;
        return 0;
    }

    priority_queue<HuffNode, vector<HuffNode*>, cmp> minHeap;

    cout << "请输入" << n << "个整数：";
    for (int i = 0; i < n; i++)
    {
        int w;
        cin >> w;
        minHeap.push(new HuffNode(w));
    }

    while (minHeap.size() > 1)
    {
        HuffNode* leftNode = minHeap.top();
        minHeap.pop();
        HuffNode* rightNode = minHeap.top();
        minHeap.pop();

        HuffNode* parent = new HuffNode(leftNode->weight + rightNode->weight);
        parent->left = leftNode;
        parent->right = rightNode;
        minHeap.push(parent);
    }

    HuffNode* root = minHeap.top();
    cout << "中序遍历结果：";
    inOrder(root);
    cout << endl;

    delTree(root);
    return 0;
}
