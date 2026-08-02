import globals from 'globals';

export default [
  {
    files: ['.build/embedded.js'],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'script',
      globals: {
        ...globals.browser,
        ...globals.es2022,
      },
    },
    rules: {
      'constructor-super': 'error',
      'for-direction': 'error',
      'getter-return': 'error',
      'no-async-promise-executor': 'error',
      'no-class-assign': 'error',
      'no-compare-neg-zero': 'error',
      'no-constant-binary-expression': 'error',
      'no-const-assign': 'error',
      'no-dupe-args': 'error',
      'no-dupe-class-members': 'error',
      'no-dupe-else-if': 'error',
      'no-dupe-keys': 'error',
      'no-fallthrough': 'error',
      'no-func-assign': 'error',
      'no-import-assign': 'error',
      'no-new-native-nonconstructor': 'error',
      'no-obj-calls': 'error',
      'no-promise-executor-return': 'error',
      'no-redeclare': 'error',
      'no-self-assign': 'error',
      'no-setter-return': 'error',
      'no-sparse-arrays': 'error',
      'no-this-before-super': 'error',
      'no-undef': 'error',
      'no-unexpected-multiline': 'error',
      'no-unreachable': 'error',
      'no-unreachable-loop': 'error',
      'no-unsafe-finally': 'error',
      'no-unsafe-negation': 'error',
      'no-unsafe-optional-chaining': 'error',
      'no-useless-backreference': 'error',
      'no-useless-catch': 'error',
      'no-useless-escape': 'error',
      'require-yield': 'error',
      'use-isnan': 'error',
      'valid-typeof': 'error'
    }
  }
];
