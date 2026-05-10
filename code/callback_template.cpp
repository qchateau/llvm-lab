extern "C" {

void sink(void*);
[[gnu::const]] void* get();

struct Data {
    [[gnu::pure]] Data* next();
};

struct State {};

using Cb = void (*)(State*, Data*);

static void callback_tpl(State* state, Data* data, Cb cb1, Cb cb2, Cb cb3)
{
    while (auto* i = data->next()) {
        cb1(state, i);
        while (auto* j = i->next()) {
            cb2(state, j);
            while (auto* k = j->next()) {
                cb3(state, k);
            }
        }
    }
}

static void noop(State*, Data*) {}

static void work1(State* state, Data*)
{
    sink(get());
}

static void work2(State* state, Data* data)
{
    if (data)
        sink(get());
}

static void cb1(State* state, Data* data)
{
    work1(state, data);
    work2(state, data);
}

void noop_callback(State* state, Data* data)
{
    callback_tpl(state, data, cb1, noop, noop);
}
}
